import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { envoyer, lire, remplacer, type S } from "../api";
import { useAuth } from "../auth";
import { STATUTS_ENCOURS } from "../libelles";
import {
  Alerte,
  Badge,
  Bouton,
  Carte,
  Champ,
  Chargement,
  DemandeMotif,
  Page,
  Saisie,
  date,
  dateHeure,
  messageErreur,
  nombre,
  useAnnuaire,
  useDonnees,
} from "../ui";

function Traitement({ encours, onEnregistre }: { encours: S["EncoursPublic"]; onEnregistre: () => void }) {
  const [recuperee, setRecuperee] = useState(encours.quantite_recuperee?.toString() ?? "");
  const [perdue, setPerdue] = useState(encours.quantite_non_recuperable?.toString() ?? "");
  const [commentaire, setCommentaire] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  const valide = /^\d+$/.test(recuperee.trim()) && /^\d+$/.test(perdue.trim());
  const total = (Number(recuperee) || 0) + (Number(perdue) || 0);
  const ecart = encours.quantite_envoyee - total;

  async function soumettre(e: FormEvent) {
    e.preventDefault();
    setEnvoi(true);
    setErreur(null);
    try {
      await remplacer(`/api/doctor-rewinder/${encours.id}/traitement`, {
        quantite_recuperee: Number(recuperee),
        quantite_non_recuperable: Number(perdue),
        commentaire: commentaire.trim() || null,
      });
      onEnregistre();
    } catch (err) {
      setErreur(messageErreur(err));
    } finally {
      setEnvoi(false);
    }
  }

  return (
    <Carte titre="Déclarer le retour du Doctor Rewinder">
      <form className="formulaire" onSubmit={soumettre}>
        <p className="champ-aide" style={{ marginTop: 0 }}>
          {nombre(encours.quantite_envoyee)} pièces ont été envoyées : chacune doit être comptée, récupérée ou perdue.
        </p>
        <div className="rangee">
          <Champ etiquette="Pièces récupérées" aide="Rectifiées, conformes : elles entreront en stock après validation.">
            <Saisie inputMode="numeric" value={recuperee} onChange={(e) => setRecuperee(e.target.value)} />
          </Champ>
          <Champ etiquette="Pièces non récupérables" aide="Perte définitive : aucune entrée en stock.">
            <Saisie inputMode="numeric" value={perdue} onChange={(e) => setPerdue(e.target.value)} />
          </Champ>
        </div>
        <Champ etiquette="Commentaire">
          <Saisie value={commentaire} onChange={(e) => setCommentaire(e.target.value)} />
        </Champ>
        {valide && ecart !== 0 && (
          <Alerte ton="alerte">
            {ecart > 0
              ? `Il manque ${nombre(ecart)} pièce(s) : le total doit être de ${nombre(encours.quantite_envoyee)}.`
              : `${nombre(-ecart)} pièce(s) de trop : le total doit être de ${nombre(encours.quantite_envoyee)}.`}
          </Alerte>
        )}
        {erreur && <Alerte>{erreur}</Alerte>}
        <div className="actions">
          <Bouton type="submit" chargement={envoi} disabled={!valide || ecart !== 0}>
            Enregistrer le retour
          </Bouton>
        </div>
      </form>
    </Carte>
  );
}

export function DoctorRewinderDetail() {
  const { id } = useParams();
  const { peut } = useAuth();
  const nom = useAnnuaire();
  const [renvoi, setRenvoi] = useState(false);
  const [probleme, setProbleme] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);

  const { donnees, erreur, chargement, recharger } = useDonnees(async () => {
    const encours = await lire<S["EncoursPublic"]>(`/api/doctor-rewinder/${id}`);
    const [ordre, modeles, articles] = await Promise.all([
      lire<S["OrdreDetail"]>(`/api/ordres-fabrication/${encours.ordre_id}`).catch(() => null),
      lire<S["ModelePublic"][]>("/api/modeles-ruban").catch(() => [] as S["ModelePublic"][]),
      lire<S["ArticlePublic"][]>("/api/articles").catch(() => [] as S["ArticlePublic"][]),
    ]);
    return {
      encours,
      ordre,
      modele: modeles.find((m) => m.id === encours.modele_id),
      article: articles.find((a) => a.id === encours.article_id),
    };
  }, [id]);

  async function valider() {
    setEnCours(true);
    setProbleme(null);
    try {
      await envoyer(`/api/doctor-rewinder/${id}/valider`);
      await recharger();
    } catch (e) {
      setProbleme(messageErreur(e));
    } finally {
      setEnCours(false);
    }
  }

  const e = donnees?.encours;
  const parCarton = e && donnees?.article?.unite_gestion !== "piece";

  return (
    <Page
      titre={donnees?.ordre ? `Doctor Rewinder — ordre ${donnees.ordre.numero}` : "Doctor Rewinder"}
      sousTitre={donnees?.modele ? `${donnees.modele.code} — ${donnees.modele.nom}` : undefined}
      actions={
        e && (
          <>
            <Badge ton={STATUTS_ENCOURS[e.statut]?.ton}>{STATUTS_ENCOURS[e.statut]?.libelle}</Badge>
            <Link to="/doctor-rewinder">← Tous les dossiers</Link>
          </>
        )
      }
    >
      <Chargement erreur={erreur} chargement={chargement}>
        {e && donnees && (
          <>
            {probleme && <Alerte>{probleme}</Alerte>}
            {e.statut === "a_valider" && peut("doctor_rewinder.valider") && (
              <div className="actions">
                <Bouton onClick={valider} chargement={enCours}>
                  Valider le traitement (entrée en stock)
                </Bouton>
                <Bouton variante="secondaire" onClick={() => setRenvoi(true)}>
                  Renvoyer pour correction
                </Bouton>
              </div>
            )}

            <div className="grille deux">
              <Carte titre="Envoi">
                <dl className="definition">
                  <dt>Ordre de fabrication</dt>
                  <dd>{donnees.ordre ? <Link to={`/production/${e.ordre_id}`}>{donnees.ordre.numero}</Link> : "—"}</dd>
                  <dt>Article</dt>
                  <dd>{donnees.article ? `${donnees.article.code} — ${donnees.article.nom}` : "—"}</dd>
                  <dt>Métrage engagé</dt>
                  <dd>{nombre(e.metrage, 0)} m</dd>
                  <dt>Pièces envoyées</dt>
                  <dd>
                    <strong>{nombre(e.quantite_envoyee)}</strong>
                  </dd>
                  <dt>Date d'envoi</dt>
                  <dd>{date(e.date_envoi)}</dd>
                </dl>
              </Carte>

              <Carte titre="Retour">
                {e.quantite_recuperee === null ? (
                  <p className="champ-aide">Le retour n'a pas encore été déclaré.</p>
                ) : (
                  <dl className="definition">
                    <dt>Pièces récupérées</dt>
                    <dd>
                      <strong>{nombre(e.quantite_recuperee)}</strong>
                    </dd>
                    <dt>Non récupérables (pertes)</dt>
                    <dd>{nombre(e.quantite_non_recuperable)}</dd>
                    <dt>Déclaré par</dt>
                    <dd>
                      {nom(e.traite_par)} le {dateHeure(e.date_traitement)}
                    </dd>
                    {e.valide_par && (
                      <>
                        <dt>Validé par</dt>
                        <dd>
                          {nom(e.valide_par)} le {dateHeure(e.valide_le)}
                        </dd>
                        <dt>Entrée en stock</dt>
                        <dd>
                          {e.mouvement_id
                            ? parCarton
                              ? `${nombre(Math.floor(e.quantite_recuperee / e.pieces_par_carton))} carton(s) complet(s)`
                              : `${nombre(e.quantite_recuperee)} pièce(s)`
                            : e.quantite_recuperee > 0
                              ? "Aucune : pas assez de pièces pour un carton complet"
                              : "Aucune (rien de récupéré)"}
                        </dd>
                        {parCarton && (e.pieces_reliquat ?? 0) > 0 && (
                          <>
                            <dt>Reliquat hors carton</dt>
                            <dd>{nombre(e.pieces_reliquat)} pièce(s), à recompléter par un prochain ordre</dd>
                          </>
                        )}
                      </>
                    )}
                    {e.commentaire && (
                      <>
                        <dt>Commentaire</dt>
                        <dd>{e.commentaire}</dd>
                      </>
                    )}
                  </dl>
                )}
              </Carte>
            </div>

            {e.statut === "en_cours" && peut("production.saisir") && (
              <Traitement key={e.cree_le} encours={e} onEnregistre={recharger} />
            )}
            {e.statut === "en_cours" && e.commentaire && <Alerte ton="alerte">{e.commentaire}</Alerte>}

            {renvoi && (
              <DemandeMotif
                titre="Renvoyer le traitement pour correction"
                consigne="Le chef de production devra déclarer de nouveau le retour. Le motif lui est montré."
                libelleAction="Renvoyer"
                onFermer={() => setRenvoi(false)}
                onConfirmer={async (motif) => {
                  await envoyer(`/api/doctor-rewinder/${id}/renvoyer`, { motif });
                  setRenvoi(false);
                  await recharger();
                }}
              />
            )}
          </>
        )}
      </Chargement>
    </Page>
  );
}
