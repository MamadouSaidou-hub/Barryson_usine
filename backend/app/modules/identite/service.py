"""Regles du module identite : connexion, sessions, comptes.

Toute ecriture du module passe par ici. Aucune dependance a HTTP : les
fonctions recoivent une session SQLAlchemy et des valeurs simples, et levent
des erreurs metier que la couche routes traduit en codes HTTP.
"""

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import journaliser, maintenant
from app.core.config import get_settings
from app.modules.identite import double_facteur, mots_de_passe
from app.modules.identite.models import Entreprise, SessionUtilisateur, TentativeConnexion, Utilisateur
from app.modules.identite.permissions import ROLES

FORMAT_IDENTIFIANT = re.compile(r"^[a-z0-9][a-z0-9._-]{2,49}$")
VERROUILLAGE_MAX = timedelta(hours=24)


class ErreurIdentite(Exception):
    message = "Opération refusée."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message


class IdentifiantsInvalides(ErreurIdentite):
    # Message unique : ne revele ni l'existence du compte ni son verrouillage.
    message = "Identifiant ou mot de passe incorrect, ou compte temporairement verrouillé."


class TropDeTentatives(ErreurIdentite):
    message = "Trop de tentatives de connexion depuis ce poste. Réessayez plus tard."


class SessionInvalide(ErreurIdentite):
    message = "Session absente ou expirée. Reconnectez-vous."


class OperationInterdite(ErreurIdentite):
    pass


class DonneesInvalides(ErreurIdentite):
    pass


class Introuvable(ErreurIdentite):
    message = "Ressource introuvable."


class Conflit(ErreurIdentite):
    pass


class CodeRequis(ErreurIdentite):
    # Le mot de passe est bon ; l'interface doit maintenant demander le code du telephone.
    message = "Saisissez le code à 6 chiffres de votre application d'authentification."


@dataclass
class SessionOuverte:
    utilisateur: Utilisateur
    jeton: str
    csrf: str
    expire_le: datetime


def hacher_jeton(jeton: str) -> str:
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()


def jeton_csrf(jeton: str) -> str:
    """Derive du jeton de session : recalculable sans etre stocke, inutilisable sans la cle serveur."""
    cle = get_settings().secret_key.encode("utf-8")
    return hmac.new(cle, b"csrf:" + jeton.encode("utf-8"), hashlib.sha256).hexdigest()


def duree_verrouillage(echecs: int, seuil: int, base_minutes: int) -> timedelta:
    """Verrouillage progressif : base au seuil, puis double a chaque nouvel echec, plafonne a 24 h."""
    if echecs < seuil:
        return timedelta(0)
    return min(timedelta(minutes=base_minutes) * 2 ** min(echecs - seuil, 16), VERROUILLAGE_MAX)


# --- Connexion -------------------------------------------------------------


def _enregistrer_echec(db: Session, identifiant: str, ip: str | None, motif: str,
                       utilisateur: Utilisateur | None) -> None:
    db.add(TentativeConnexion(identifiant=identifiant, ip=ip, reussie=False, motif=motif))
    journaliser(
        db, "connexion.echec",
        cible_type="utilisateurs" if utilisateur else None,
        cible_id=utilisateur.id if utilisateur else None,
        apres={"identifiant": identifiant, "motif": motif},
        acteur_id=None,
        entreprise_id=utilisateur.entreprise_id if utilisateur else None,
    )
    # Valide avant de lever l'erreur : l'echec doit compter meme si la requete echoue.
    db.commit()


def double_facteur_requis(utilisateur: Utilisateur) -> bool:
    return utilisateur.role in get_settings().roles_double_facteur


def double_facteur_a_configurer(utilisateur: Utilisateur) -> bool:
    return double_facteur_requis(utilisateur) and not utilisateur.double_facteur_actif


def _compter_echec(utilisateur: Utilisateur, instant: datetime) -> timedelta:
    reglages = get_settings()
    utilisateur.echecs_consecutifs += 1
    duree = duree_verrouillage(utilisateur.echecs_consecutifs, reglages.connexion_seuil_echecs_compte,
                               reglages.connexion_verrouillage_minutes)
    if duree:
        utilisateur.verrouille_jusqu_a = instant + duree
    return duree


def connecter(db: Session, identifiant: str, mot_de_passe: str, *, ip: str | None,
              user_agent: str | None, code: str | None = None) -> SessionOuverte:
    reglages = get_settings()
    instant = maintenant()
    identifiant = identifiant.strip().lower()[:150]
    db.info["ip"] = ip

    if ip is not None:
        depuis = instant - timedelta(minutes=reglages.connexion_fenetre_ip_minutes)
        echecs_ip = db.scalar(
            select(func.count()).select_from(TentativeConnexion).where(
                TentativeConnexion.ip == ip,
                TentativeConnexion.reussie.is_(False),
                TentativeConnexion.horodatage >= depuis,
            )
        )
        if echecs_ip >= reglages.connexion_max_echecs_ip:
            _enregistrer_echec(db, identifiant, ip, "ip_limitee", None)
            raise TropDeTentatives()

    # FOR UPDATE : deux tentatives simultanees ne perdent pas d'increment du compteur.
    utilisateur = db.scalar(
        select(Utilisateur).where(Utilisateur.identifiant == identifiant).with_for_update()
    )

    if utilisateur is None:
        mots_de_passe.verifier_factice(mot_de_passe)
        _enregistrer_echec(db, identifiant, ip, "identifiant_inconnu", None)
        raise IdentifiantsInvalides()

    if utilisateur.verrouille_jusqu_a is not None and utilisateur.verrouille_jusqu_a > instant:
        mots_de_passe.verifier_factice(mot_de_passe)
        _enregistrer_echec(db, identifiant, ip, "compte_verrouille", utilisateur)
        raise IdentifiantsInvalides()

    if not mots_de_passe.verifier(utilisateur.mot_de_passe_hash, mot_de_passe):
        _compter_echec(utilisateur, instant)
        _enregistrer_echec(db, identifiant, ip, "mot_de_passe_incorrect", utilisateur)
        raise IdentifiantsInvalides()

    # Verifie apres le mot de passe : un compte desactive ne se distingue pas d'un mauvais mot de passe.
    if not utilisateur.actif:
        _enregistrer_echec(db, identifiant, ip, "compte_inactif", utilisateur)
        raise IdentifiantsInvalides()

    if double_facteur_requis(utilisateur) and utilisateur.double_facteur_actif:
        if not code:
            db.rollback()  # libere le verrou de ligne, rien n'a change
            raise CodeRequis()
        secret = dechiffrer_secret(utilisateur)
        pas = secret and double_facteur.verifier_code(secret, code, instant, utilisateur.totp_dernier_pas)
        if not pas:
            # Meme compteur que le mot de passe : 1 chance sur un million par essai, 5 essais.
            _compter_echec(utilisateur, instant)
            _enregistrer_echec(db, identifiant, ip, "code_incorrect", utilisateur)
            raise IdentifiantsInvalides()
        utilisateur.totp_dernier_pas = pas

    utilisateur.echecs_consecutifs = 0
    utilisateur.verrouille_jusqu_a = None
    utilisateur.derniere_connexion_le = instant
    if mots_de_passe.doit_rehacher(utilisateur.mot_de_passe_hash):
        utilisateur.mot_de_passe_hash = mots_de_passe.hacher(mot_de_passe)

    db.info.update(acteur_id=utilisateur.id, entreprise_id=utilisateur.entreprise_id)
    db.add(TentativeConnexion(identifiant=identifiant, ip=ip, reussie=True, motif="ok"))
    journaliser(db, "connexion.reussie", cible_type="utilisateurs", cible_id=utilisateur.id)
    ouverte = _ouvrir_session(db, utilisateur, ip=ip, user_agent=user_agent, instant=instant)
    db.commit()
    return ouverte


def _ouvrir_session(db: Session, utilisateur: Utilisateur, *, ip: str | None, user_agent: str | None,
                    instant: datetime) -> SessionOuverte:
    reglages = get_settings()
    # Nouveau jeton a chaque connexion : pas de fixation de session possible.
    jeton = secrets.token_urlsafe(32)
    session = SessionUtilisateur(
        utilisateur_id=utilisateur.id,
        entreprise_id=utilisateur.entreprise_id,
        jeton_hash=hacher_jeton(jeton),
        cree_le=instant,
        derniere_activite_le=instant,
        expire_le=instant + timedelta(hours=reglages.session_duree_max_heures),
        ip=ip,
        user_agent=(user_agent or "")[:255] or None,
    )
    db.add(session)
    db.flush()
    actives = db.scalars(
        select(SessionUtilisateur)
        .where(SessionUtilisateur.utilisateur_id == utilisateur.id,
               SessionUtilisateur.revoquee_le.is_(None),
               SessionUtilisateur.expire_le > instant)
        .order_by(SessionUtilisateur.cree_le.desc(), SessionUtilisateur.id)
    ).all()
    for ancienne in actives[reglages.sessions_max_par_utilisateur:]:
        if ancienne.id != session.id:
            ancienne.revoquee_le = instant
    return SessionOuverte(utilisateur, jeton, jeton_csrf(jeton), session.expire_le)


def authentifier(db: Session, jeton: str | None) -> tuple[Utilisateur, SessionUtilisateur]:
    if not jeton or len(jeton) > 128:
        raise SessionInvalide()
    reglages = get_settings()
    instant = maintenant()
    ligne = db.execute(
        select(SessionUtilisateur, Utilisateur)
        .join(Utilisateur, Utilisateur.id == SessionUtilisateur.utilisateur_id)
        .where(SessionUtilisateur.jeton_hash == hacher_jeton(jeton))
    ).first()
    if ligne is None:
        raise SessionInvalide()
    session, utilisateur = ligne
    inactivite = timedelta(minutes=reglages.session_inactivite_minutes)
    if (
        session.revoquee_le is not None
        or session.expire_le <= instant
        or session.derniere_activite_le + inactivite <= instant
        or not utilisateur.actif
        or session.cree_le < utilisateur.mot_de_passe_modifie_le
    ):
        raise SessionInvalide()
    # Mise a jour au plus une fois par minute : evite une ecriture a chaque requete.
    if instant - session.derniere_activite_le > timedelta(minutes=1):
        session.derniere_activite_le = instant
        db.commit()
    return utilisateur, session


def deconnecter(db: Session, session: SessionUtilisateur) -> None:
    session.revoquee_le = maintenant()
    journaliser(db, "deconnexion", cible_type="utilisateurs", cible_id=session.utilisateur_id)
    db.commit()


def _revoquer_sessions(db: Session, utilisateur_id: uuid.UUID, instant: datetime) -> None:
    db.execute(
        update(SessionUtilisateur)
        .where(SessionUtilisateur.utilisateur_id == utilisateur_id, SessionUtilisateur.revoquee_le.is_(None))
        .values(revoquee_le=instant)
    )


def changer_mot_de_passe(db: Session, utilisateur: Utilisateur, actuel: str, nouveau: str, *,
                         ip: str | None, user_agent: str | None) -> SessionOuverte:
    instant = maintenant()
    if not mots_de_passe.verifier(utilisateur.mot_de_passe_hash, actuel):
        # Une session volee ne doit pas permettre de deviner le mot de passe sans limite :
        # meme compteur que la connexion, et au seuil la session tombe avec le verrouillage.
        duree = _compter_echec(utilisateur, instant)
        journaliser(db, "mot_de_passe.changement_refuse", cible_type="utilisateurs", cible_id=utilisateur.id,
                    apres={"echecs_consecutifs": utilisateur.echecs_consecutifs, "verrouillage": bool(duree)})
        if duree:
            _revoquer_sessions(db, utilisateur.id, instant)
        db.commit()
        if duree:
            raise SessionInvalide()
        raise DonneesInvalides("Le mot de passe actuel est incorrect.")
    erreurs = mots_de_passe.verifier_politique(
        nouveau, identifiant=utilisateur.identifiant, nom=utilisateur.nom
    )
    if erreurs:
        raise DonneesInvalides(" ".join(erreurs))
    if mots_de_passe.verifier(utilisateur.mot_de_passe_hash, nouveau):
        raise DonneesInvalides("Le nouveau mot de passe doit être différent de l'actuel.")

    utilisateur.mot_de_passe_hash = mots_de_passe.hacher(nouveau)
    utilisateur.mot_de_passe_modifie_le = instant
    utilisateur.doit_changer_mot_de_passe = False
    # Toutes les sessions tombent, y compris la courante : une nouvelle est emise.
    _revoquer_sessions(db, utilisateur.id, instant)
    journaliser(db, "mot_de_passe.changement", cible_type="utilisateurs", cible_id=utilisateur.id)
    ouverte = _ouvrir_session(db, utilisateur, ip=ip, user_agent=user_agent, instant=instant)
    db.commit()
    return ouverte


# --- Administration des comptes --------------------------------------------
# Point de passage unique du filtrage par entreprise (decision 0002).


def _utilisateurs_de(entreprise_id: uuid.UUID):
    return select(Utilisateur).where(Utilisateur.entreprise_id == entreprise_id)


def _charger(db: Session, acteur: Utilisateur, utilisateur_id: uuid.UUID) -> Utilisateur:
    # Hors de l'entreprise de l'acteur : introuvable, pas interdit (ne confirme pas l'existence).
    cible = db.scalar(_utilisateurs_de(acteur.entreprise_id).where(Utilisateur.id == utilisateur_id))
    if cible is None:
        raise Introuvable()
    return cible


def lister_utilisateurs(db: Session, acteur: Utilisateur) -> list[Utilisateur]:
    return list(db.scalars(_utilisateurs_de(acteur.entreprise_id).order_by(Utilisateur.nom)))


def _verifier_identifiant(identifiant: str) -> str:
    identifiant = identifiant.strip().lower()
    if not FORMAT_IDENTIFIANT.match(identifiant):
        raise DonneesInvalides(
            "Identifiant invalide : 3 à 50 caractères, minuscules, chiffres, point, tiret ou souligné."
        )
    return identifiant


def creer_utilisateur(db: Session, acteur: Utilisateur, *, identifiant: str, nom: str,
                      role: str) -> tuple[Utilisateur, str]:
    identifiant = _verifier_identifiant(identifiant)
    if role not in ROLES:
        raise DonneesInvalides("Rôle inconnu.")
    if db.scalar(select(Utilisateur.id).where(Utilisateur.identifiant == identifiant)) is not None:
        raise Conflit("Cet identifiant est déjà utilisé.")
    temporaire = mots_de_passe.generer_temporaire()
    instant = maintenant()
    utilisateur = Utilisateur(
        entreprise_id=acteur.entreprise_id,
        identifiant=identifiant,
        nom=nom.strip(),
        role=role,
        mot_de_passe_hash=mots_de_passe.hacher(temporaire),
        actif=True,
        doit_changer_mot_de_passe=True,
        mot_de_passe_modifie_le=instant,
        cree_le=instant,
        cree_par=acteur.id,
    )
    db.add(utilisateur)
    try:
        db.commit()
    except IntegrityError as erreur:
        db.rollback()
        raise Conflit("Cet identifiant est déjà utilisé.") from erreur
    return utilisateur, temporaire


def modifier_utilisateur(db: Session, acteur: Utilisateur, utilisateur_id: uuid.UUID, *,
                         nom: str | None = None, role: str | None = None,
                         actif: bool | None = None) -> Utilisateur:
    cible = _charger(db, acteur, utilisateur_id)
    if cible.id == acteur.id and ((role is not None and role != cible.role) or actif is False):
        # Empeche l'auto-promotion et le verrouillage du dernier acces d'administration.
        raise OperationInterdite("Vous ne pouvez pas modifier votre propre rôle ni désactiver votre compte.")
    if role is not None and role not in ROLES:
        raise DonneesInvalides("Rôle inconnu.")
    droits_reduits = (role is not None and role != cible.role) or (actif is False and cible.actif)
    if nom is not None:
        cible.nom = nom.strip()
    if role is not None:
        cible.role = role
    if actif is not None:
        cible.actif = actif
    if droits_reduits:
        # Un changement de role ou une desactivation prend effet immediatement.
        _revoquer_sessions(db, cible.id, maintenant())
    db.commit()
    return cible


def reinitialiser_mot_de_passe(db: Session, acteur: Utilisateur, utilisateur_id: uuid.UUID) -> str:
    cible = _charger(db, acteur, utilisateur_id)
    if cible.id == acteur.id:
        raise OperationInterdite("Utilisez le changement de mot de passe pour votre propre compte.")
    instant = maintenant()
    temporaire = mots_de_passe.generer_temporaire()
    cible.mot_de_passe_hash = mots_de_passe.hacher(temporaire)
    cible.mot_de_passe_modifie_le = instant
    cible.doit_changer_mot_de_passe = True
    cible.echecs_consecutifs = 0
    cible.verrouille_jusqu_a = None
    _revoquer_sessions(db, cible.id, instant)
    journaliser(db, "mot_de_passe.reinitialisation", cible_type="utilisateurs", cible_id=cible.id)
    db.commit()
    return temporaire


# --- Double authentification -----------------------------------------------


def dechiffrer_secret(utilisateur: Utilisateur) -> str | None:
    if not utilisateur.totp_secret_chiffre:
        return None
    return double_facteur.dechiffrer(utilisateur.totp_secret_chiffre, utilisateur.id)


def initialiser_double_facteur(db: Session, utilisateur: Utilisateur) -> tuple[str, str]:
    """Genere un nouveau secret, actif seulement apres confirmation par un premier code."""
    if utilisateur.double_facteur_actif:
        raise OperationInterdite("Double authentification déjà active : demandez une réinitialisation "
                                 "à l'administrateur en cas de changement de téléphone.")
    secret = double_facteur.generer_secret()
    utilisateur.totp_secret_chiffre = double_facteur.chiffrer(secret, utilisateur.id)
    utilisateur.totp_dernier_pas = None
    db.commit()
    return secret, double_facteur.uri_configuration(secret, utilisateur.identifiant)


def activer_double_facteur(db: Session, utilisateur: Utilisateur, code: str) -> None:
    secret = dechiffrer_secret(utilisateur)
    if utilisateur.double_facteur_actif or secret is None:
        raise OperationInterdite("Aucune configuration en attente.")
    pas = double_facteur.verifier_code(secret, code, maintenant(), utilisateur.totp_dernier_pas)
    if not pas:
        journaliser(db, "double_facteur.activation_refusee", cible_type="utilisateurs",
                    cible_id=utilisateur.id)
        db.commit()
        raise DonneesInvalides("Code incorrect. Vérifiez l'heure du téléphone et réessayez.")
    utilisateur.double_facteur_actif = True
    utilisateur.totp_dernier_pas = pas
    db.commit()


def _effacer_double_facteur(db: Session, cible: Utilisateur) -> None:
    cible.totp_secret_chiffre = None
    cible.double_facteur_actif = False
    cible.totp_dernier_pas = None
    _revoquer_sessions(db, cible.id, maintenant())
    journaliser(db, "double_facteur.reinitialisation", cible_type="utilisateurs", cible_id=cible.id)
    db.commit()


def reinitialiser_double_facteur(db: Session, acteur: Utilisateur, utilisateur_id: uuid.UUID) -> None:
    """Telephone perdu : la personne reconfigure a sa prochaine connexion."""
    cible = _charger(db, acteur, utilisateur_id)
    if cible.id == acteur.id:
        raise OperationInterdite("Un autre administrateur doit réinitialiser votre double authentification.")
    _effacer_double_facteur(db, cible)


def reinitialiser_double_facteur_par_console(db: Session, identifiant: str) -> None:
    """Dernier recours (seul administrateur sans telephone) : exige un acces au serveur."""
    cible = db.scalar(select(Utilisateur).where(Utilisateur.identifiant == identifiant.strip().lower()))
    if cible is None:
        raise Introuvable("Aucun compte avec cet identifiant.")
    db.info.update(acteur_id=None, entreprise_id=cible.entreprise_id, ip="console")
    _effacer_double_facteur(db, cible)


def journaliser_verification(db: Session, resultat: dict) -> None:
    journaliser(db, "audit.verification",
                apres={k: resultat[k] for k in ("integre", "entrees_verifiees", "premiere_anomalie")})
    db.commit()


def amorcer(db: Session, *, nom_entreprise: str, identifiant: str, nom: str,
            mot_de_passe: str) -> Utilisateur:
    """Cree l'entreprise et le premier administrateur. Impossible une fois un compte existant :
    aucun compte par defaut, aucun mot de passe connu d'avance."""
    if db.scalar(select(func.count()).select_from(Utilisateur)):
        raise OperationInterdite("Déjà initialisé : créez les comptes depuis l'administration.")
    identifiant = _verifier_identifiant(identifiant)
    erreurs = mots_de_passe.verifier_politique(mot_de_passe, identifiant=identifiant, nom=nom)
    if erreurs:
        raise DonneesInvalides(" ".join(erreurs))
    entreprise = db.scalar(select(Entreprise).where(Entreprise.nom == nom_entreprise.strip()))
    if entreprise is None:
        entreprise = Entreprise(nom=nom_entreprise.strip())
        db.add(entreprise)
        db.flush()
    instant = maintenant()
    administrateur = Utilisateur(
        entreprise_id=entreprise.id,
        identifiant=identifiant,
        nom=nom.strip(),
        role="administrateur",
        mot_de_passe_hash=mots_de_passe.hacher(mot_de_passe),
        actif=True,
        doit_changer_mot_de_passe=False,
        mot_de_passe_modifie_le=instant,
        cree_le=instant,
    )
    db.add(administrateur)
    db.flush()
    journaliser(db, "amorcage", cible_type="utilisateurs", cible_id=administrateur.id,
                acteur_id=None, entreprise_id=entreprise.id)
    db.commit()
    return administrateur
