"""Journal d'audit en ajout seul, chaine par hash (ADR 0004).

Deux facons d'y ecrire :
- automatiquement : tout modele qui herite de `Audite` produit une entree a
  chaque creation, modification ou suppression, sans que le module y pense ;
- explicitement : `journaliser()` pour les evenements qui ne sont pas une
  ligne de table (connexion, acces refuse, reinitialisation...).

Chaque entree porte un numero sans trou et
`entry_hash = sha256(prev_hash || json_canonique(contenu))`. Le numero et le
hash sont attribues au moment du flush, sous un verrou transactionnel
PostgreSQL : deux transactions concurrentes ne peuvent pas obtenir le meme
numero ni chainer sur le meme predecesseur. La base refuse en plus toute
modification ou suppression (triggers poses par la migration).
"""

import hashlib
import hmac
import itertools
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, String, event, inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.cles import deriver_cle
from app.core.db import Base

HASH_ORIGINE = "0" * 64
MASQUE = "***"
# Cle arbitraire mais fixe du verrou consultatif qui serialise l'ecriture du journal.
_CLE_VERROU_JOURNAL = 7_201_461_001
_compteur_creation = itertools.count()
_NON_FOURNI: Any = object()


def maintenant() -> datetime:
    return datetime.now(UTC)


def json_canonique(valeur: Any) -> str:
    return json.dumps(valeur, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _normaliser(valeur: Any) -> Any:
    """Forme exacte qui sera relue depuis JSONB : le hash recalcule doit correspondre."""
    return None if valeur is None else json.loads(json_canonique(valeur))


def calculer_hash(prev_hash: str, contenu: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + json_canonique(contenu)).encode("utf-8")).hexdigest()


class JournalAudit(Base):
    __tablename__ = "journal_audit"
    __table_args__ = (Index("ix_journal_audit_entreprise_numero", "entreprise_id", "numero"),)

    numero: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    horodatage: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Pas de cle etrangere : le journal doit survivre a tout, y compris a une
    # erreur de manipulation sur les tables qu'il decrit.
    entreprise_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    acteur_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(80))
    cible_type: Mapped[str | None] = mapped_column(String(80))
    cible_id: Mapped[str | None] = mapped_column(String(80))
    avant: Mapped[dict | None] = mapped_column(JSONB)
    apres: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(45))
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), unique=True)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._ordre_creation = next(_compteur_creation)

    def contenu_signe(self) -> dict[str, Any]:
        return {
            "numero": self.numero,
            "horodatage": self.horodatage.astimezone(UTC).isoformat(),
            "entreprise_id": str(self.entreprise_id) if self.entreprise_id else None,
            "acteur_id": str(self.acteur_id) if self.acteur_id else None,
            "action": self.action,
            "cible_type": self.cible_type,
            "cible_id": self.cible_id,
            "avant": self.avant,
            "apres": self.apres,
            "ip": self.ip,
        }


def journaliser(
    session: Session,
    action: str,
    *,
    cible_type: str | None = None,
    cible_id: Any = None,
    avant: dict[str, Any] | None = None,
    apres: dict[str, Any] | None = None,
    acteur_id: Any = _NON_FOURNI,
    entreprise_id: Any = _NON_FOURNI,
) -> JournalAudit:
    """Ajoute une entree au journal. Elle est numerotee et chainee au prochain flush.

    Acteur, entreprise et IP viennent par defaut de `session.info`, renseigne
    par la dependance d'authentification. Ne jamais passer de secret ici.
    """
    info = session.info
    entree = JournalAudit(
        horodatage=maintenant(),
        entreprise_id=info.get("entreprise_id") if entreprise_id is _NON_FOURNI else entreprise_id,
        acteur_id=info.get("acteur_id") if acteur_id is _NON_FOURNI else acteur_id,
        action=action,
        cible_type=cible_type,
        cible_id=None if cible_id is None else str(cible_id),
        avant=_normaliser(avant),
        apres=_normaliser(apres),
        ip=info.get("ip"),
    )
    session.add(entree)
    return entree


class Audite:
    """Marqueur : les ecritures sur ce modele sont journalisees automatiquement.

    `__audit_ignore__` : colonnes techniques dont le changement seul ne merite
    pas d'entree (compteurs, horodatage de derniere connexion...).
    `__audit_masque__` : colonnes dont on trace le changement sans la valeur.
    """

    __audit_ignore__: frozenset[str] = frozenset()
    __audit_masque__: frozenset[str] = frozenset()

    def entreprise_audit(self) -> Any:
        return getattr(self, "entreprise_id", None)


def _instantane(obj: Audite) -> dict[str, Any]:
    etat = inspect(obj)
    valeurs = {}
    for attr in etat.mapper.column_attrs:
        if attr.key in obj.__audit_ignore__:
            continue
        valeurs[attr.key] = MASQUE if attr.key in obj.__audit_masque__ else getattr(obj, attr.key)
    return valeurs


def _changements(obj: Audite) -> tuple[dict[str, Any], dict[str, Any]]:
    etat = inspect(obj)
    avant, apres = {}, {}
    for attr in etat.mapper.column_attrs:
        if attr.key in obj.__audit_ignore__:
            continue
        historique = etat.attrs[attr.key].history
        if not historique.has_changes():
            continue
        ancien = historique.deleted[0] if historique.deleted else None
        nouveau = historique.added[0] if historique.added else None
        if ancien == nouveau:
            continue
        if attr.key in obj.__audit_masque__:
            ancien, nouveau = MASQUE, MASQUE
        avant[attr.key], apres[attr.key] = ancien, nouveau
    return avant, apres


def _cible(obj: Audite) -> tuple[str, Any]:
    return obj.__tablename__, getattr(obj, "id", None)  # type: ignore[attr-defined]


@event.listens_for(Session, "after_flush")
def _journaliser_ecritures(session: Session, _contexte: Any) -> None:
    # En after_flush, les valeurs par defaut et les cles sont connues, et
    # l'historique des attributs reflete encore l'etat d'avant le flush. Les
    # entrees ajoutees ici partent au flush suivant, que commit() declenche.
    for obj in session.new:
        if isinstance(obj, Audite):
            table, cle = _cible(obj)
            journaliser(session, f"{table}.creation", cible_type=table, cible_id=cle,
                        apres=_instantane(obj), entreprise_id=obj.entreprise_audit())
    for obj in session.dirty:
        if isinstance(obj, Audite) and session.is_modified(obj, include_collections=False):
            avant, apres = _changements(obj)
            if apres:
                table, cle = _cible(obj)
                journaliser(session, f"{table}.modification", cible_type=table, cible_id=cle,
                            avant=avant, apres=apres, entreprise_id=obj.entreprise_audit())
    for obj in session.deleted:
        if isinstance(obj, Audite):
            table, cle = _cible(obj)
            journaliser(session, f"{table}.suppression", cible_type=table, cible_id=cle,
                        avant=_instantane(obj), entreprise_id=obj.entreprise_audit())


@event.listens_for(Session, "before_flush")
def _chainer_entrees(session: Session, _contexte: Any, _instances: Any) -> None:
    en_attente = sorted(
        (o for o in session.new if isinstance(o, JournalAudit) and o.entry_hash is None),
        key=lambda o: o._ordre_creation,
    )
    if not en_attente:
        return
    connexion = session.connection()
    # Verrou tenu jusqu'a la fin de la transaction : serialise les ecrivains.
    connexion.execute(text("SELECT pg_advisory_xact_lock(:cle)"), {"cle": _CLE_VERROU_JOURNAL})
    dernier = connexion.execute(
        text("SELECT numero, entry_hash FROM journal_audit ORDER BY numero DESC LIMIT 1")
    ).first()
    numero, precedent = (dernier.numero, dernier.entry_hash) if dernier else (0, HASH_ORIGINE)
    for entree in en_attente:
        numero += 1
        entree.numero = numero
        entree.prev_hash = precedent
        entree.entry_hash = calculer_hash(precedent, entree.contenu_signe())
        precedent = entree.entry_hash


def verifier_chaine(session: Session) -> dict[str, Any]:
    """Recalcule toute la chaine. Detecte une ligne alteree, inseree ou retiree au milieu.

    Une troncature des dernieres entrees ne se voit pas par la chaine seule :
    c'est pourquoi `dernier_hash` doit etre consigne regulierement hors de la
    base (scelle quotidien, voir ADR 0004).
    """
    precedent, attendu, verifiees = HASH_ORIGINE, 1, 0
    requete = select(JournalAudit).order_by(JournalAudit.numero).execution_options(yield_per=500)
    for entree in session.scalars(requete):
        if (
            entree.numero != attendu
            or entree.prev_hash != precedent
            or calculer_hash(precedent, entree.contenu_signe()) != entree.entry_hash
        ):
            return {"integre": False, "entrees_verifiees": verifiees,
                    "premiere_anomalie": entree.numero, "dernier_hash": precedent}
        precedent, attendu, verifiees = entree.entry_hash, attendu + 1, verifiees + 1
    return {"integre": True, "entrees_verifiees": verifiees, "premiere_anomalie": None,
            "dernier_hash": precedent}


# --- Scelles : detection d'une troncature en fin de journal ----------------
# Un scelle (dernier numero + son hash, signe) est exporte regulierement HORS du
# serveur. Plus tard, si cette entree a disparu ou change, le journal a ete
# tronque ou reecrit, meme si la chaine restante parait coherente.


def _signer(contenu: dict[str, Any]) -> str:
    return hmac.new(deriver_cle("scelle-audit"), json_canonique(contenu).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def sceller(session: Session) -> dict[str, Any]:
    dernier = session.scalar(select(JournalAudit).order_by(JournalAudit.numero.desc()).limit(1))
    contenu = {
        "numero": dernier.numero if dernier else 0,
        "entry_hash": dernier.entry_hash if dernier else HASH_ORIGINE,
        "scelle_le": maintenant().isoformat(),
    }
    return {**contenu, "signature": _signer(contenu)}


def verifier_scelle(session: Session, scelle: dict[str, Any]) -> str | None:
    """Renvoie None si le scelle est respecte, sinon la description de l'anomalie."""
    contenu = {k: scelle.get(k) for k in ("numero", "entry_hash", "scelle_le")}
    if not hmac.compare_digest(str(scelle.get("signature", "")), _signer(contenu)):
        return "scelle invalide : signature incorrecte (scelle falsifie ou SECRET_KEY changee)"
    if contenu["numero"] == 0:
        return None
    numero, date = contenu["numero"], contenu["scelle_le"]
    entree = session.get(JournalAudit, numero)
    if entree is None:
        return f"entree {numero} absente : journal tronque apres le scelle du {date}"
    if entree.entry_hash != contenu["entry_hash"]:
        return f"entree {numero} differente de celle scellee le {date}"
    return None
