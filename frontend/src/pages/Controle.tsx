import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { envoyer, lire, type S } from "../api";
import { useAuth } from "../auth";
import { STATUTS_RECEPTION } from "../libelles";
import {
  Alerte,
  Badge,
  Bouton,
  Carte,
  Champ,
  Chargement,
  Page,
  Saisie,
  Tableau,
  date,
  dateHeure,
  messageErreur,
  nombre,
  useAnnuaire,
  useDonnees,
} from "../ui";

type Decision = "acceptee" | "acceptee_avec_reserves" | "refusee";

const DECISIONS: { valeur: Decision; libelle: string; aide: string }[] = [
  { valeur: "acceptee", libelle: "Acceptée", aide: "Tout est conforme : quantités, documents, état." },
  { valeur: "acceptee_avec_reserves", libelle: "Acceptée avec réserves", aide: "On garde ce qui est conforme et on note les écarts." },
  { valeur: "refusee", libelle: "Refusée", aide: "Rien n'entre en stock." },
];

export function Controle() {
  const { id } = useParams();
  const { peut } = useAuth();
  const nom = useAnnuaire();
  const { donnees, erreur, chargement, recharger } = useDonnees(async () => {
    const reception = await lire<S["ReceptionDetail"]>(`/api/receptions-achat/${id}`);
    // Les numeros de bobines servent a verifier les bobines refusees ; sans droit sur le stock, on s'en passe.
    const importation = reception.import_colisage_id
      ? await lire<S["ImportDetail"]>(`/api/imports-colisage/${reception.import_colisage_id}`).catch(() => null)
      : null;
    return { reception, importation };
  }, [id]);

  const [documentsOk, setDocumentsOk] = useState(true);
  const [decision, setDecision] = useState<Decision>("acceptee");
  const [commentaire, setCommentaire] = useState("");
  const [acceptees, setAcceptees] = useState<Record<string, string>>({});
  const [motifs, setMotifs] = useState<Record<string, string>>({});
  const [refusees, setRefusees] = useState<Record<string, string>>({});
  const [probleme, setProbleme] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  const r = donnees?.reception;
  const modifiable = r?.statut === "en_controle" && peut("stock.valider_reception");

  const numerosImportes = new Set(donnees?.importation?.lignes.map((l) => l.numero_fournisseur) ?? []);
  const listeRefusees = (ligneId: string) =>
    (refusees[ligneId] ?? "").split(/[\s,;]+/).filter(Boolean);

  function acceptee(l: S["LigneReceptionPublic"]): number {
    if (decision === "refusee") return 0;
    if (l.unite === "rouleau") return l.quantite_recue - listeRefusees(l.id).length;
    return acceptees[l.id] === undefined || acceptees[l.id] === "" ? l.quantite_recue : Number(acceptees[l.id].replace(",", "."));
  }

  const ecart = !!r && (!documentsOk || r.lignes.some((l) => acceptee(l) < l.quantite_recue));

  async function valider() {
    if (!r) return;
    setEnvoi(true);
    setProbleme(null);
    try {
      await envoyer(`/api/receptions-achat/${id}/controle`, {
        decision,
        controle_documentaire_ok: documentsOk,
        commentaire: commentaire || null,
        lignes: r.lignes.map((l) => ({
          ligne_reception_id: l.id,
          quantite_acceptee: l.unite === "rouleau" ? l.quantite_recue - listeRefusees(l.id).length : acceptee(l),
          motif_ecart: motifs[l.id] || null,
          bobines_refusees: l.unite === "rouleau" ? listeRefusees(l.id) : [],
        })),
      });
      await recharger();
    } catch (e) {
      setProbleme(messageErreur(e));
    } finally {
      setEnvoi(false);
    }
  }

  return (
    <Page
      titre={r ? `Arrivée ${r.numero}` : "Arrivée"}
      sousTitre={r?.conteneur_reference ? `Conteneur ${r.conteneur_reference}` : undefined}
      actions={
        r && (
          <>
            <Badge ton={STATUTS_RECEPTION[r.statut]?.ton}>{STATUTS_RECEPTION[r.statut]?.libelle}</Badge>
            <Link to={`/commandes/${r.commande_id}`}>← Voir la commande</Link>
          </>
        )
      }
    >
      <Chargement erreur={erreur} chargement={chargement}>
        {r && (
          <>
            {r.statut === "en_controle" && (
              <Alerte ton="alerte">
                Cette marchandise <strong>n'est pas encore en stock</strong>. Elle y entrera, pour les seules quantités
                acceptées, quand le contrôle sera validé.
              </Alerte>
            )}
            {r.avertissements.length > 0 && (
              <Alerte ton="alerte">
                <strong>À vérifier avant de décider :</strong>
                <ul>
                  {r.avertissements.map((a) => (
                    <li key={a}>{a}</li>
                  ))}
                </ul>
              </Alerte>
            )}

            <Carte titre="Livraison">
              <dl className="definition">
                <dt>Arrivée</dt>
                <dd>{date(r.date_arrivee)}</dd>
                <dt>Facture / bon de livraison</dt>
                <dd>{r.numero_facture ?? "—"}</dd>
                <dt>Enregistrée par</dt>
                <dd>
                  {nom(r.cree_par)} le {dateHeure(r.cree_le)}
                </dd>
                {r.commentaire && (
                  <>
                    <dt>Observation à l'arrivée</dt>
                    <dd>{r.commentaire}</dd>
                  </>
                )}
                {r.controle_par && (
                  <>
                    <dt>Contrôlée par</dt>
                    <dd>
                      {nom(r.controle_par)} le {dateHeure(r.controle_le)} — documents {r.controle_documentaire_ok ? "conformes" : "non conformes"}
                    </dd>
                    {r.commentaire_controle && (
                      <>
                        <dt>Commentaire du contrôle</dt>
                        <dd>{r.commentaire_controle}</dd>
                      </>
                    )}
                  </>
                )}
              </dl>
            </Carte>

            <Carte titre="Contrôle quantitatif">
              <Tableau
                colonnes={[
                  "Article",
                  { texte: "Commandé", droite: true },
                  { texte: "Solde avant", droite: true },
                  { texte: "Reçu", droite: true },
                  { texte: "Accepté", droite: true },
                  "Écart / observation",
                ]}
              >
                {r.lignes.map((l) => {
                  const bobinesRefusees = modifiable ? listeRefusees(l.id) : l.bobines_refusees;
                  const inconnues = bobinesRefusees.filter((n) => numerosImportes.size > 0 && !numerosImportes.has(n));
                  const aCompter = modifiable ? acceptee(l) : l.quantite_acceptee;
                  return (
                    <tr key={l.id} className={aCompter !== null && aCompter < l.quantite_recue ? "attention" : ""}>
                      <td>
                        <strong>{l.article_code}</strong>
                        <div className="champ-aide">{l.article_nom}</div>
                      </td>
                      <td className="droite">{nombre(l.quantite_commandee, 1)}</td>
                      <td className="droite">{nombre(l.solde_avant, 1)}</td>
                      <td className="droite">
                        {nombre(l.quantite_recue, 1)} {l.unite}
                      </td>
                      <td className="droite" style={{ width: 150 }}>
                        {modifiable && l.unite !== "rouleau" && decision !== "refusee" ? (
                          <Saisie aria-label="Quantité acceptée" className="saisie droite" inputMode="decimal" value={acceptees[l.id] ?? String(l.quantite_recue)} onChange={(e) => setAcceptees({ ...acceptees, [l.id]: e.target.value })} />
                        ) : (
                          <strong>{aCompter === null ? "—" : nombre(aCompter, 1)}</strong>
                        )}
                      </td>
                      <td style={{ minWidth: 300 }}>
                        {modifiable ? (
                          <div className="formulaire" style={{ gap: 6 }}>
                            {l.unite === "rouleau" && decision !== "refusee" && (
                              <>
                                <Saisie aria-label="Bobines refusées" placeholder="N° des bobines refusées (ex. 12, 47)" value={refusees[l.id] ?? ""} onChange={(e) => setRefusees({ ...refusees, [l.id]: e.target.value })} />
                                {inconnues.length > 0 && <span className="champ-erreur">Absente(s) de la packing list : {inconnues.join(", ")}</span>}
                              </>
                            )}
                            {decision === "acceptee_avec_reserves" && (
                              <Saisie aria-label="Motif de l'écart" placeholder="Motif de l'écart" value={motifs[l.id] ?? ""} onChange={(e) => setMotifs({ ...motifs, [l.id]: e.target.value })} />
                            )}
                            {l.observation && <span className="champ-aide">{l.observation}</span>}
                          </div>
                        ) : (
                          <>
                            {l.bobines_refusees.length > 0 && <div>Bobines refusées : {l.bobines_refusees.join(", ")}</div>}
                            {l.motif_ecart && <div>{l.motif_ecart}</div>}
                            {l.observation && <div className="champ-aide">{l.observation}</div>}
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </Tableau>
            </Carte>

            {modifiable && (
              <Carte titre="Votre décision">
                <div className="formulaire">
                  <label className="case">
                    <input type="checkbox" checked={documentsOk} onChange={(e) => setDocumentsOk(e.target.checked)} />
                    <span>
                      <strong>Documents conformes</strong> (facture, packing list, bon de livraison concordent avec la commande)
                    </span>
                  </label>
                  <div className="pastille-decision">
                    {DECISIONS.map((d) => (
                      <label key={d.valeur} className={decision === d.valeur ? "choisi" : ""}>
                        <input type="radio" name="decision" checked={decision === d.valeur} onChange={() => setDecision(d.valeur)} />
                        <span>
                          <strong>{d.libelle}</strong>
                          <div className="champ-aide">{d.aide}</div>
                        </span>
                      </label>
                    ))}
                  </div>
                  {decision === "acceptee" && ecart && (
                    <Alerte ton="alerte">Un écart est constaté : choisissez « Acceptée avec réserves » ou « Refusée ».</Alerte>
                  )}
                  {decision === "acceptee_avec_reserves" && !ecart && (
                    <Alerte ton="info">Aucun écart constaté : la réception est simplement « Acceptée ».</Alerte>
                  )}
                  {decision !== "acceptee" && (
                    <Champ etiquette="Commentaire du contrôle" aide="Obligatoire pour une acceptation avec réserves ou un refus.">
                      <textarea className="saisie" rows={3} value={commentaire} onChange={(e) => setCommentaire(e.target.value)} />
                    </Champ>
                  )}
                  {probleme && <Alerte>{probleme}</Alerte>}
                  <div className="actions">
                    <Bouton onClick={valider} chargement={envoi} variante={decision === "refusee" ? "danger" : "primaire"}>
                      {decision === "refusee" ? "Refuser la marchandise" : "Valider le contrôle et enregistrer en stock"}
                    </Bouton>
                  </div>
                </div>
              </Carte>
            )}

            {r.statut !== "en_controle" && (
              <Alerte ton={r.statut === "refusee" ? "danger" : "ok"}>
                Contrôle terminé : décision définitive.{" "}
                {r.lot_id ? (
                  <>
                    La marchandise est en stock — <Link to="/stock/lots">voir les lots et bobines</Link>.
                  </>
                ) : (
                  r.statut === "refusee" && "Rien n'est entré en stock."
                )}
              </Alerte>
            )}
          </>
        )}
      </Chargement>
    </Page>
  );
}
