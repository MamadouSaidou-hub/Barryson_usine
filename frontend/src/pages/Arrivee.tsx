import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { envoyer, lire, type S } from "../api";
import { useAuth } from "../auth";
import { PackingList, type PackingPrete } from "../composants/PackingList";
import { Alerte, Bouton, Carte, Chargement, DemandeMotif, Page, Saisie, Tableau, messageErreur, nombre, useDonnees } from "../ui";

type LigneCommande = S["CommandeDetail"]["lignes"][number];

// Reception d'une commande en UN seul ecran : on compare avec ce qu'on a commande, on coche ce qui est
// conforme, on corrige le reste, et on valide. L'arrivee ET le controle sont enregistres d'un coup.
export function Arrivee() {
  const { id } = useParams();
  const aller = useNavigate();
  const { peut } = useAuth();
  const { donnees, erreur, chargement } = useDonnees(() => lire<S["CommandeDetail"]>(`/api/commandes-achat/${id}`), [id]);

  const aujourdhui = new Date().toISOString().slice(0, 10);
  const [dateArrivee, setDateArrivee] = useState(aujourdhui);
  const [facture, setFacture] = useState("");
  const [recues, setRecues] = useState<Record<string, string>>({});
  const [conformes, setConformes] = useState<Record<string, boolean>>({});
  const [gardees, setGardees] = useState<Record<string, string>>({});
  const [remarques, setRemarques] = useState<Record<string, string>>({});
  const [refusees, setRefusees] = useState<Record<string, string>>({});
  const [documentsOk, setDocumentsOk] = useState(false);
  const [noteDocuments, setNoteDocuments] = useState("");
  const [packing, setPacking] = useState<PackingPrete | null>(null);
  const [refus, setRefus] = useState(false);
  const [probleme, setProbleme] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  if (chargement || erreur || !donnees) {
    return (
      <Page titre="Recevoir la marchandise">
        <Chargement erreur={erreur} chargement={chargement}>
          {null}
        </Chargement>
      </Page>
    );
  }

  const commande = donnees;
  const ouverte = ["commandee", "partiellement_recue"].includes(commande.statut);
  const lignes = commande.lignes.filter((l) => l.solde > 0);
  const peutControler = peut("stock.valider_reception");
  const bobines = lignes.find((l) => l.unite === "rouleau");

  const nb = (v: string | undefined) => {
    const t = (v ?? "").replace(",", ".").trim();
    return t === "" ? NaN : Number(t);
  };
  // Ce qui est arrive : par defaut, tout le reste a recevoir. Les bobines se comptent par la packing list.
  const recue = (l: LigneCommande): number => {
    if (l.unite === "rouleau") return packing?.nombre ?? 0;
    const v = recues[l.id];
    return v === undefined ? l.solde : nb(v);
  };
  const bobinesRefusees = (l: LigneCommande) => (refusees[l.id] ?? "").split(/[\s,;]+/).filter(Boolean);
  const gardee = (l: LigneCommande): number => {
    if (conformes[l.id]) return recue(l);
    if (l.unite === "rouleau") return recue(l) - bobinesRefusees(l).length;
    const g = nb(gardees[l.id]);
    return Number.isNaN(g) ? 0 : g;
  };
  const arrivee = (l: LigneCommande) => recue(l) > 0;
  const traitee = (l: LigneCommande): boolean => {
    if (!arrivee(l)) return true; // rien arrive sur cette ligne : elle reste a recevoir
    if (conformes[l.id]) return true;
    if ((remarques[l.id] ?? "").trim().length < 5) return false;
    if (l.unite === "rouleau") return bobinesRefusees(l).length > 0 && bobinesRefusees(l).length <= recue(l);
    return gardee(l) >= 0 && gardee(l) < recue(l);
  };

  const presentes = lignes.filter(arrivee);
  const quantitesValides = lignes.every((l) => l.unite === "rouleau" || !Number.isNaN(recue(l)) && recue(l) >= 0);
  const bobinesPretes = !bobines || recue(bobines) === 0 || packing !== null;
  const toutTraite = presentes.every(traitee) && (documentsOk || noteDocuments.trim().length >= 5);
  const ecart = !documentsOk || presentes.some((l) => gardee(l) < recue(l));
  const totalGarde = presentes.reduce((s, l) => s + gardee(l), 0);
  const decision = totalGarde === 0 ? "refusee" : ecart ? "acceptee_avec_reserves" : "acceptee";
  const toutCoche = presentes.length > 0 && presentes.every((l) => conformes[l.id]) && documentsOk;
  const pret = ouverte && presentes.length > 0 && quantitesValides && bobinesPretes && (peutControler ? toutTraite && totalGarde > 0 : true);

  function toutCocher() {
    setConformes(Object.fromEntries(lignes.map((l) => [l.id, true])));
    setDocumentsOk(true);
  }

  async function valider(motifRefus?: string) {
    setEnvoi(true);
    setProbleme(null);
    let reception: S["ReceptionDetail"] | null = null;
    try {
      reception = await envoyer<S["ReceptionDetail"]>(`/api/commandes-achat/${id}/receptions`, {
        date_arrivee: dateArrivee,
        numero_facture: facture.trim() || null,
        commentaire: null,
        import_colisage_id: bobines && recue(bobines) > 0 ? packing!.importId : null,
        lignes: presentes.map((l) =>
          l.unite === "rouleau" ? { ligne_commande_id: l.id } : { ligne_commande_id: l.id, quantite_recue: String(recue(l)) },
        ),
      });
      if (!peutControler) {
        aller(`/receptions/${reception.id}`);
        return;
      }
      const notes = [
        ...presentes.filter((l) => !conformes[l.id]).map((l) => `${l.article_code} : ${remarques[l.id]?.trim()}`),
        ...(documentsOk ? [] : [`Documents : ${noteDocuments.trim()}`]),
      ];
      await envoyer(`/api/receptions-achat/${reception.id}/controle`, {
        decision: motifRefus ? "refusee" : decision,
        controle_documentaire_ok: documentsOk,
        commentaire: motifRefus ?? (notes.length > 0 ? notes.join(" ; ") : null),
        lignes: reception.lignes.map((rl) => {
          const l = lignes.find((x) => x.id === rl.ligne_commande_id)!;
          const conforme = !!conformes[l.id] && !motifRefus;
          return {
            ligne_reception_id: rl.id,
            quantite_acceptee: motifRefus ? 0 : gardee(l),
            motif_ecart: conforme ? null : remarques[l.id]?.trim() || null,
            bobines_refusees: l.unite === "rouleau" && !conforme && !motifRefus ? bobinesRefusees(l) : [],
          };
        }),
      });
      aller(`/receptions/${reception.id}`);
    } catch (err) {
      // L'arrivee peut etre deja enregistree : on l'indique, et le controle se termine depuis la liste des arrivees.
      setProbleme(
        messageErreur(err) + (reception ? " L'arrivée est enregistrée : vous pouvez terminer le contrôle depuis « Recevoir »." : ""),
      );
      setEnvoi(false);
    }
  }

  return (
    <Page
      titre={`Recevoir la marchandise — ${commande.numero}`}
      sousTitre="Comparez avec ce que vous avez commandé, cochez ce qui est conforme. Rien n'entre en stock avant votre validation."
      actions={<Link to={`/commandes/${id}`}>← Retour à la commande</Link>}
    >
      {!ouverte && <Alerte ton="alerte">Cette commande n'attend pas de marchandise.</Alerte>}

      <Carte>
        <div className="rangee">
          <label className="champ">
            <span className="champ-etiquette">Date d'arrivée</span>
            <Saisie type="date" max={aujourdhui} value={dateArrivee} onChange={(e) => setDateArrivee(e.target.value)} />
          </label>
          <label className="champ">
            <span className="champ-etiquette">N° de facture ou bon de livraison</span>
            <Saisie value={facture} onChange={(e) => setFacture(e.target.value)} />
          </label>
        </div>
      </Carte>

      <Carte
        titre="Ce que nous avons commandé"
        droite={
          peutControler && (
            <Bouton type="button" variante="secondaire" onClick={toutCocher} disabled={toutCoche}>
              ✓ Tout cocher
            </Bouton>
          )
        }
      >
        <Tableau
          colonnes={[
            ...(peutControler ? ["Conforme"] : []),
            "Article",
            { texte: "Commandé", droite: true },
            { texte: "Reste à recevoir", droite: true },
            { texte: "Reçu", droite: true },
            ...(peutControler ? ["S'il y a un problème"] : []),
          ]}
        >
          {lignes.map((l) => {
            const bobine = l.unite === "rouleau";
            const coche = !!conformes[l.id];
            const present = arrivee(l);
            return (
              <tr key={l.id} className={peutControler && present && !coche ? "attention" : ""}>
                {peutControler && (
                  <td style={{ width: 90, textAlign: "center" }}>
                    <input
                      type="checkbox"
                      aria-label={`${l.article_code} conforme`}
                      style={{ width: 22, height: 22 }}
                      checked={coche && present}
                      disabled={!present}
                      onChange={(e) => setConformes({ ...conformes, [l.id]: e.target.checked })}
                    />
                  </td>
                )}
                <td>
                  <strong>{l.article_nom}</strong>
                  <div className="champ-aide">{l.article_code}</div>
                </td>
                <td className="droite">{nombre(l.quantite_commandee, 1)}</td>
                <td className="droite">
                  {nombre(l.solde, 1)} {l.unite}
                </td>
                <td className="droite" style={{ width: 140 }}>
                  {bobine ? (
                    <strong>{packing ? `${packing.nombre} bobines` : "— (packing list ci-dessous)"}</strong>
                  ) : (
                    <Saisie
                      aria-label="Quantité reçue"
                      className="saisie droite"
                      inputMode="decimal"
                      value={recues[l.id] ?? String(l.solde)}
                      onChange={(e) => setRecues({ ...recues, [l.id]: e.target.value })}
                    />
                  )}
                </td>
                {peutControler && (
                  <td style={{ minWidth: 280 }}>
                    {!present || coche ? null : (
                      <div className="formulaire" style={{ gap: 6 }}>
                        <Saisie
                          aria-label="Quel problème ?"
                          placeholder="Quel problème ? (ex. 200 tubes écrasés)"
                          value={remarques[l.id] ?? ""}
                          onChange={(e) => setRemarques({ ...remarques, [l.id]: e.target.value })}
                        />
                        {bobine ? (
                          <Saisie
                            aria-label="Bobines refusées"
                            placeholder="N° des bobines refusées (ex. 12, 47)"
                            value={refusees[l.id] ?? ""}
                            onChange={(e) => setRefusees({ ...refusees, [l.id]: e.target.value })}
                          />
                        ) : (
                          <Saisie
                            aria-label="Quantité conforme"
                            inputMode="decimal"
                            placeholder="Quantité conforme que l'on garde (ex. 4700)"
                            value={gardees[l.id] ?? ""}
                            onChange={(e) => setGardees({ ...gardees, [l.id]: e.target.value })}
                          />
                        )}
                      </div>
                    )}
                  </td>
                )}
              </tr>
            );
          })}
          {peutControler && (
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
          )}
        </Tableau>
        {lignes.length === 0 && <p className="champ-aide">Tout ce qui était commandé a déjà été reçu.</p>}
      </Carte>

      {bobines && (
        <Carte titre="Packing list des bobines">
          {packing ? (
            <Alerte ton="ok">
              Conteneur <strong>{packing.conteneur}</strong> : <strong>{packing.nombre} bobines</strong>.{" "}
              <Bouton type="button" variante="lien" onClick={() => setPacking(null)}>
                Modifier
              </Bouton>
            </Alerte>
          ) : (
            <PackingList
              fournisseurId={commande.fournisseur_id}
              articleId={bobines.article_id}
              dateArrivee={dateArrivee}
              finitionAttendue={bobines.couleur_finition}
              onPrete={setPacking}
              onAnnulee={() => undefined}
            />
          )}
        </Carte>
      )}

      {probleme && <Alerte>{probleme}</Alerte>}
      <div className="actions">
        <Bouton onClick={() => valider()} chargement={envoi} disabled={!pret}>
          {!peutControler ? "Enregistrer l'arrivée" : !ecart ? "Tout est conforme : enregistrer en stock" : "Enregistrer en stock ce qui est conforme"}
        </Bouton>
        {peutControler && (
          <Bouton type="button" variante="danger" disabled={!ouverte || presentes.length === 0 || !bobinesPretes} onClick={() => setRefus(true)}>
            Refuser toute la marchandise
          </Bouton>
        )}
      </div>
      {peutControler && !toutTraite && presentes.length > 0 && (
        <p className="champ-aide">Cochez chaque ligne conforme, ou dites quel est le problème pour les autres.</p>
      )}

      {refus && (
        <DemandeMotif
          titre="Refuser toute la marchandise"
          consigne="Rien n'entrera en stock. Dites pourquoi : le motif est conservé."
          libelleAction="Refuser"
          onFermer={() => setRefus(false)}
          onConfirmer={async (motif) => {
            await valider(motif);
            setRefus(false);
          }}
        />
      )}
    </Page>
  );
}
