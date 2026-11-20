import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { envoyer, lire, type S } from "../api";
import { useAuth } from "../auth";
import { FINITIONS, STATUTS_COMMANDE, STATUTS_RECEPTION } from "../libelles";
import {
  Alerte,
  Badge,
  Bouton,
  Carte,
  Chargement,
  DemandeMotif,
  Page,
  Tableau,
  Vide,
  date,
  dateHeure,
  messageErreur,
  montant,
  nombre,
  useAnnuaire,
  useDonnees,
} from "../ui";

type Action = "refuser" | "annuler" | "solder";

const TITRES: Record<Action, { titre: string; consigne: string; bouton: string }> = {
  refuser: { titre: "Refuser la commande", consigne: "Le motif sera visible de la personne qui l'a préparée.", bouton: "Refuser" },
  annuler: { titre: "Annuler la commande", consigne: "Une commande annulée ne peut plus être reprise.", bouton: "Annuler la commande" },
  solder: {
    titre: "Solder la commande",
    consigne: "Le reliquat ne sera pas livré (ou est abandonné) : la commande sera clôturée en l'état.",
    bouton: "Solder",
  },
};

export function CommandeDetail() {
  const { id } = useParams();
  const aller = useNavigate();
  const { session, peut } = useAuth();
  const nom = useAnnuaire();
  const [action, setAction] = useState<Action | null>(null);
  const [probleme, setProbleme] = useState<string | null>(null);
  const [enCours, setEnCours] = useState<string | null>(null);

  const { donnees, erreur, chargement, recharger } = useDonnees(async () => {
    const [commande, fournisseurs] = await Promise.all([
      lire<S["CommandeDetail"]>(`/api/commandes-achat/${id}`),
      lire<S["FournisseurPublic"][]>("/api/fournisseurs"),
    ]);
    return { commande, fournisseur: fournisseurs.find((f) => f.id === commande.fournisseur_id) };
  }, [id]);

  async function etape(chemin: string, corps?: unknown) {
    setEnCours(chemin);
    setProbleme(null);
    try {
      await envoyer(`/api/commandes-achat/${id}/${chemin}`, corps);
      await recharger();
    } catch (e) {
      setProbleme(messageErreur(e));
    } finally {
      setEnCours(null);
    }
  }

  const c = donnees?.commande;
  const statut = c?.statut ?? "";
  const peutValider = peut("achats.valider");
  const parDelegation = session!.permissions_deleguees.includes("achats.valider");
  const soi = session!.utilisateur.id;
  const sonAuteur = c?.cree_par === soi;

  return (
    <Page
      titre={c ? `Commande ${c.numero}` : "Commande"}
      sousTitre={donnees?.fournisseur?.nom}
      actions={
        c && (
          <>
            <Badge ton={STATUTS_COMMANDE[statut]?.ton}>{STATUTS_COMMANDE[statut]?.libelle}</Badge>
            <Link to="/commandes">← Toutes les commandes</Link>
          </>
        )
      }
    >
      <Chargement erreur={erreur} chargement={chargement}>
        {c && donnees && (
          <>
            {probleme && <Alerte>{probleme}</Alerte>}

            {statut === "soumise" && peutValider && (
              <Alerte ton="alerte">
                {sonAuteur ? (
                  <>Vous avez préparé cette commande : elle doit être validée par une autre personne.</>
                ) : (
                  <>
                    Cette commande attend votre décision
                    {parDelegation && <> — vous validez <strong>au nom du Directeur général</strong> (délégation)</>}.
                  </>
                )}
              </Alerte>
            )}

            <div className="actions">
              {statut === "brouillon" && peut("achats.saisir") && (
                <Bouton onClick={() => etape("soumettre")} chargement={enCours === "soumettre"}>
                  Soumettre au Directeur général
                </Bouton>
              )}
              {statut === "soumise" && peutValider && !sonAuteur && (
                <>
                  <Bouton onClick={() => etape("valider")} chargement={enCours === "valider"}>
                    {parDelegation ? "Valider au nom du DG" : "Valider la commande"}
                  </Bouton>
                  <Bouton variante="danger" onClick={() => setAction("refuser")}>
                    Refuser
                  </Bouton>
                </>
              )}
              {statut === "validee" && peut("achats.saisir") && (
                <Bouton onClick={() => etape("commander")} chargement={enCours === "commander"}>
                  Passer commande au fournisseur
                </Bouton>
              )}
              {(statut === "commandee" || statut === "partiellement_recue") && peut("stock.saisir") && (
                <Bouton onClick={() => aller(`/commandes/${id}/arrivee`)}>Enregistrer une arrivée</Bouton>
              )}
              {statut === "partiellement_recue" && peut("achats.saisir") && (
                <Bouton variante="secondaire" onClick={() => setAction("solder")}>
                  Solder le reliquat
                </Bouton>
              )}
              {["brouillon", "soumise", "validee", "commandee"].includes(statut) && (peut("achats.saisir") || peutValider) && (
                <Bouton variante="secondaire" onClick={() => setAction("annuler")}>
                  Annuler
                </Bouton>
              )}
            </div>

            <div className="grille deux">
              <Carte titre="Conditions">
                <dl className="definition">
                  <dt>Devise</dt>
                  <dd>{c.devise}</dd>
                  {c.devise !== "GNF" && (
                    <>
                      <dt>Taux du jour</dt>
                      <dd>{c.taux_change_gnf ? `1 ${c.devise} = ${nombre(c.taux_change_gnf, 2)} GNF` : "non renseigné"}</dd>
                    </>
                  )}
                  <dt>Arrivée prévue</dt>
                  <dd>{date(c.date_arrivee_prevue)}</dd>
                  <dt>Référence fournisseur</dt>
                  <dd>{c.reference_fournisseur ?? "—"}</dd>
                  <dt>Préparée par</dt>
                  <dd>
                    {nom(c.cree_par)} le {dateHeure(c.cree_le)}
                  </dd>
                  {c.valide_par && (
                    <>
                      <dt>Validée par</dt>
                      <dd>
                        {nom(c.valide_par)} le {dateHeure(c.valide_le)}
                        {c.valide_via_delegation_id && <> <Badge ton="info">par délégation du DG</Badge></>}
                      </dd>
                    </>
                  )}
                  {c.motif_decision && (
                    <>
                      <dt>Motif</dt>
                      <dd>{c.motif_decision}</dd>
                    </>
                  )}
                  {c.commentaire && (
                    <>
                      <dt>Commentaire</dt>
                      <dd>{c.commentaire}</dd>
                    </>
                  )}
                </dl>
              </Carte>

              <Carte titre="Montant">
                <p className="indicateur" style={{ margin: 0 }}>
                  <span className="valeur">{c.montant_total === null ? "—" : montant(c.montant_total, c.devise)}</span>
                  {c.montant_total_gnf !== null && c.devise !== "GNF" && (
                    <span className="legende">soit environ {montant(c.montant_total_gnf, "GNF")}</span>
                  )}
                  {c.prix_manquants > 0 && (
                    <span className="legende">{c.prix_manquants} ligne(s) sans prix : total partiel.</span>
                  )}
                </p>
              </Carte>
            </div>

            <Carte titre="Lignes">
              <Tableau
                colonnes={[
                  "Article",
                  { texte: "Commandé", droite: true },
                  { texte: "Reçu et accepté", droite: true },
                  { texte: "Reste à recevoir", droite: true },
                  { texte: "Prix unitaire", droite: true },
                  { texte: "Montant", droite: true },
                ]}
              >
                {c.lignes.map((l) => (
                  <tr key={l.id}>
                    <td>
                      <strong>{l.article_code}</strong> — {l.article_nom}
                      {l.couleur_finition && <div className="champ-aide">Finition : {FINITIONS[l.couleur_finition]}</div>}
                    </td>
                    <td className="droite">
                      {nombre(l.quantite_commandee, 1)} {l.unite}
                    </td>
                    <td className="droite">{nombre(l.quantite_recue_acceptee, 1)}</td>
                    <td className="droite">
                      {l.solde === 0 ? <Badge ton="ok">Complet</Badge> : nombre(l.solde, 1)}
                    </td>
                    <td className="droite">{l.prix_unitaire === null ? "—" : montant(l.prix_unitaire, c.devise)}</td>
                    <td className="droite">{l.montant === null ? "—" : montant(l.montant, c.devise)}</td>
                  </tr>
                ))}
              </Tableau>
            </Carte>

            <div className="grille deux">
              <Carte titre="Arrivées">
                {c.receptions.length === 0 ? (
                  <Vide>Aucune marchandise arrivée pour le moment.</Vide>
                ) : (
                  <Tableau colonnes={["Réception", "Conteneur", "Arrivée", "État"]}>
                    {c.receptions.map((r) => (
                      <tr key={r.id}>
                        <td>
                          <Link to={`/receptions/${r.id}`}>{r.numero}</Link>
                        </td>
                        <td>{r.conteneur_reference ?? "—"}</td>
                        <td>{date(r.date_arrivee)}</td>
                        <td>
                          <Badge ton={STATUTS_RECEPTION[r.statut]?.ton}>{STATUTS_RECEPTION[r.statut]?.libelle}</Badge>
                        </td>
                      </tr>
                    ))}
                  </Tableau>
                )}
              </Carte>

              <Carte titre="Historique">
                <ul className="historique">
                  {c.transitions.map((t, i) => (
                    <li key={i}>
                      <span className="quand">{dateHeure(t.cree_le)}</span>
                      <span>
                        <strong>{STATUTS_COMMANDE[t.vers_statut]?.libelle ?? t.vers_statut}</strong> — {nom(t.acteur_id)}
                        {t.motif && <div className="champ-aide">{t.motif}</div>}
                      </span>
                    </li>
                  ))}
                </ul>
              </Carte>
            </div>

            {action && (
              <DemandeMotif
                titre={TITRES[action].titre}
                consigne={TITRES[action].consigne}
                libelleAction={TITRES[action].bouton}
                ton={action === "solder" ? "primaire" : "danger"}
                onFermer={() => setAction(null)}
                onConfirmer={async (motif) => {
                  await envoyer(`/api/commandes-achat/${id}/${action}`, { motif });
                  setAction(null);
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
