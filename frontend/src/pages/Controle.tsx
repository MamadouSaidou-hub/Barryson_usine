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
  Chargement,
  DemandeMotif,
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

type Ligne = S["LigneReceptionPublic"];

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

  // Une case cochee = "conforme, tel que reçu". Decochee : on dit pourquoi et ce qu'on garde quand même.
  const [conformes, setConformes] = useState<Record<string, boolean>>({});
  const [documentsOk, setDocumentsOk] = useState(false);
  const [noteDocuments, setNoteDocuments] = useState("");
  const [acceptees, setAcceptees] = useState<Record<string, string>>({});
  const [remarques, setRemarques] = useState<Record<string, string>>({});
  const [refusees, setRefusees] = useState<Record<string, string>>({});
  const [refus, setRefus] = useState(false);
  const [probleme, setProbleme] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  const r = donnees?.reception;
  const modifiable = r?.statut === "en_controle" && peut("stock.valider_reception");
  const numerosImportes = new Set(donnees?.importation?.lignes.map((l) => l.numero_fournisseur) ?? []);

  const bobinesRefusees = (l: Ligne) => (refusees[l.id] ?? "").split(/[\s,;]+/).filter(Boolean);
  const nombreSaisi = (l: Ligne) => {
    const v = (acceptees[l.id] ?? "").replace(",", ".").trim();
    return v === "" ? 0 : Number(v);
  };
  function acceptee(l: Ligne): number {
    if (conformes[l.id]) return l.quantite_recue;
    return l.unite === "rouleau" ? l.quantite_recue - bobinesRefusees(l).length : nombreSaisi(l);
  }
  // Une ligne decochee est "traitee" quand tout est dit : pourquoi, et ce qu'on garde.
  function ligneTraitee(l: Ligne): boolean {
    if (conformes[l.id]) return true;
    if ((remarques[l.id] ?? "").trim().length < 5) return false;
    if (l.unite === "rouleau") return bobinesRefusees(l).length > 0 && bobinesRefusees(l).length <= l.quantite_recue;
    const q = nombreSaisi(l);
    return Number.isFinite(q) && q >= 0 && q < l.quantite_recue;
  }

  const lignes = r?.lignes ?? [];
  const toutTraite = lignes.every(ligneTraitee) && (documentsOk || noteDocuments.trim().length >= 5);
  const ecart = !documentsOk || lignes.some((l) => acceptee(l) < l.quantite_recue);
  const totalAccepte = lignes.reduce((somme, l) => somme + acceptee(l), 0);
  const decision = totalAccepte === 0 ? "refusee" : ecart ? "acceptee_avec_reserves" : "acceptee";
  const toutCoche = lignes.length > 0 && lignes.every((l) => conformes[l.id]) && documentsOk;

  function toutCocher() {
    setConformes(Object.fromEntries(lignes.map((l) => [l.id, true])));
    setDocumentsOk(true);
  }

  const inconnues = (l: Ligne) => bobinesRefusees(l).filter((n) => numerosImportes.size > 0 && !numerosImportes.has(n));

  async function enregistrer(forcerRefus?: string) {
    if (!r) return;
    setEnvoi(true);
    setProbleme(null);
    const notes = [
      ...lignes.filter((l) => !conformes[l.id]).map((l) => `${l.article_code} : ${remarques[l.id]?.trim()}`),
      ...(documentsOk ? [] : [`Documents : ${noteDocuments.trim()}`]),
    ];
    try {
      await envoyer(`/api/receptions-achat/${id}/controle`, {
        decision: forcerRefus ? "refusee" : decision,
        controle_documentaire_ok: documentsOk,
        commentaire: forcerRefus ?? (notes.length > 0 ? notes.join(" ; ") : null),
        lignes: lignes.map((l) => {
          const conforme = !!conformes[l.id] && !forcerRefus;
          return {
            ligne_reception_id: l.id,
            quantite_acceptee: forcerRefus ? 0 : acceptee(l),
            motif_ecart: conforme ? null : remarques[l.id]?.trim() || null,
            bobines_refusees: l.unite === "rouleau" && !conforme && !forcerRefus ? bobinesRefusees(l) : [],
          };
        }),
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
              <Alerte ton="info">
                Comparez avec la commande, cochez ce qui est conforme. Rien n'entre en stock avant votre validation.
              </Alerte>
            )}
            {r.avertissements.length > 0 && (
              <Alerte ton="alerte">
                <strong>À vérifier :</strong>
                <ul>
                  {r.avertissements.map((a) => (
                    <li key={a}>{a}</li>
                  ))}
                </ul>
              </Alerte>
            )}

            {modifiable ? (
              <Carte
                titre="Vérification de la marchandise"
                droite={
                  <Bouton type="button" variante="secondaire" onClick={toutCocher} disabled={toutCoche}>
                    ✓ Tout cocher
                  </Bouton>
                }
              >
                <Tableau
                  colonnes={[
                    "Conforme",
                    "Article",
                    { texte: "Commandé", droite: true },
                    { texte: "Reçu", droite: true },
                    { texte: "On garde", droite: true },
                    "S'il y a un problème",
                  ]}
                >
                  {lignes.map((l) => {
                    const coche = !!conformes[l.id];
                    const bobine = l.unite === "rouleau";
                    return (
                      <tr key={l.id} className={coche ? "" : "attention"}>
                        <td style={{ width: 90, textAlign: "center" }}>
                          <input
                            type="checkbox"
                            aria-label={`${l.article_code} conforme`}
                            style={{ width: 22, height: 22 }}
                            checked={coche}
                            onChange={(e) => setConformes({ ...conformes, [l.id]: e.target.checked })}
                          />
                        </td>
                        <td>
                          <strong>{l.article_nom}</strong>
                          <div className="champ-aide">{l.article_code}</div>
                        </td>
                        <td className="droite">{nombre(l.quantite_commandee, 1)}</td>
                        <td className="droite">
                          {nombre(l.quantite_recue, 1)} {l.unite}
                        </td>
                        <td className="droite" style={{ width: 130 }}>
                          {coche || bobine ? (
                            <strong>{nombre(acceptee(l), 1)}</strong>
                          ) : (
                            <Saisie
                              aria-label="Quantité gardée"
                              className="saisie droite"
                              inputMode="decimal"
                              value={acceptees[l.id] ?? ""}
                              placeholder="0"
                              onChange={(e) => setAcceptees({ ...acceptees, [l.id]: e.target.value })}
                            />
                          )}
                        </td>
                        <td style={{ minWidth: 260 }}>
                          {coche ? (
                            l.observation ? <span className="champ-aide">{l.observation}</span> : null
                          ) : (
                            <div className="formulaire" style={{ gap: 6 }}>
                              <Saisie
                                aria-label="Quel problème ?"
                                placeholder="Quel problème ? (ex. 200 tubes écrasés)"
                                value={remarques[l.id] ?? ""}
                                onChange={(e) => setRemarques({ ...remarques, [l.id]: e.target.value })}
                              />
                              {bobine && (
                                <Saisie
                                  aria-label="Bobines refusées"
                                  placeholder="N° des bobines refusées (ex. 12, 47)"
                                  value={refusees[l.id] ?? ""}
                                  onChange={(e) => setRefusees({ ...refusees, [l.id]: e.target.value })}
                                />
                              )}
                              {bobine && inconnues(l).length > 0 && (
                                <span className="champ-erreur">Absente(s) de la packing list : {inconnues(l).join(", ")}</span>
                              )}
                              {l.observation && <span className="champ-aide">{l.observation}</span>}
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                  <tr className={documentsOk ? "" : "attention"}>
                    <td style={{ textAlign: "center" }}>
                      <input
                        type="checkbox"
                        aria-label="Documents conformes"
                        style={{ width: 22, height: 22 }}
                        checked={documentsOk}
                        onChange={(e) => setDocumentsOk(e.target.checked)}
                      />
                    </td>
                    <td colSpan={4}>
                      <strong>Documents conformes</strong>
                      <div className="champ-aide">Facture, packing list et bon de livraison concordent avec la commande.</div>
                    </td>
                    <td>
                      {!documentsOk && (
                        <Saisie
                          aria-label="Problème de documents"
                          placeholder="Quel problème ? (ex. facture manquante)"
                          value={noteDocuments}
                          onChange={(e) => setNoteDocuments(e.target.value)}
                        />
                      )}
                    </td>
                  </tr>
                </Tableau>

                {probleme && <Alerte>{probleme}</Alerte>}
                <div className="actions" style={{ marginTop: 14 }}>
                  <Bouton onClick={() => enregistrer()} chargement={envoi} disabled={!toutTraite || totalAccepte === 0}>
                    {!ecart ? "Tout est conforme : enregistrer en stock" : "Enregistrer en stock ce qui est conforme"}
                  </Bouton>
                  <Bouton type="button" variante="danger" onClick={() => setRefus(true)}>
                    Refuser toute la marchandise
                  </Bouton>
                </div>
                {!toutTraite && (
                  <p className="champ-aide" style={{ marginBottom: 0 }}>
                    Cochez chaque ligne conforme, ou dites quel est le problème pour les autres.
                  </p>
                )}
              </Carte>
            ) : (
              <Carte titre="Marchandise reçue">
                <Tableau
                  colonnes={[
                    "Article",
                    { texte: "Commandé", droite: true },
                    { texte: "Reçu", droite: true },
                    { texte: "Gardé", droite: true },
                    "Remarque",
                  ]}
                >
                  {lignes.map((l) => (
                    <tr key={l.id} className={l.quantite_acceptee !== null && l.quantite_acceptee < l.quantite_recue ? "attention" : ""}>
                      <td>
                        <strong>{l.article_nom}</strong>
                        <div className="champ-aide">{l.article_code}</div>
                      </td>
                      <td className="droite">{nombre(l.quantite_commandee, 1)}</td>
                      <td className="droite">
                        {nombre(l.quantite_recue, 1)} {l.unite}
                      </td>
                      <td className="droite">
                        <strong>{l.quantite_acceptee === null ? "—" : nombre(l.quantite_acceptee, 1)}</strong>
                      </td>
                      <td>
                        {l.bobines_refusees.length > 0 && <div>Bobines refusées : {l.bobines_refusees.join(", ")}</div>}
                        {l.motif_ecart && <div>{l.motif_ecart}</div>}
                        {l.observation && <div className="champ-aide">{l.observation}</div>}
                      </td>
                    </tr>
                  ))}
                </Tableau>
              </Carte>
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

            {r.statut !== "en_controle" && (
              <Alerte ton={r.statut === "refusee" ? "danger" : "ok"}>
                Contrôle terminé : décision définitive.{" "}
                {r.lot_id ? (
                  <>
                    La marchandise est en stock — <Link to="/stock/lots">voir les bobines</Link>.
                  </>
                ) : (
                  r.statut === "refusee" && "Rien n'est entré en stock."
                )}
              </Alerte>
            )}

            {refus && (
              <DemandeMotif
                titre="Refuser toute la marchandise"
                consigne="Rien n'entrera en stock. Dites pourquoi : le motif est conservé."
                libelleAction="Refuser"
                onFermer={() => setRefus(false)}
                onConfirmer={async (motif) => {
                  await enregistrer(motif);
                  setRefus(false);
                }}
              />
            )}
          </>
        )}
      </Chargement>
    </Page>
  );
}
