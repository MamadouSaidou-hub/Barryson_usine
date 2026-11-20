import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { envoyer, lire, type S } from "../api";
import { PackingList, type PackingPrete } from "../composants/PackingList";
import { Alerte, Bouton, Carte, Champ, Chargement, Page, Saisie, messageErreur, nombre, useDonnees } from "../ui";

export function Arrivee() {
  const { id } = useParams();
  const aller = useNavigate();
  const { donnees, erreur, chargement } = useDonnees(() => lire<S["CommandeDetail"]>(`/api/commandes-achat/${id}`), [id]);

  const aujourdhui = new Date().toISOString().slice(0, 10);
  const [dateArrivee, setDateArrivee] = useState(aujourdhui);
  const [facture, setFacture] = useState("");
  const [commentaire, setCommentaire] = useState("");
  const [inclus, setInclus] = useState<Record<string, boolean>>({});
  const [quantites, setQuantites] = useState<Record<string, string>>({});
  const [packing, setPacking] = useState<PackingPrete | null>(null);
  const [problemes, setProblemes] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  if (chargement || erreur || !donnees) {
    return (
      <Page titre="Enregistrer une arrivée">
        <Chargement erreur={erreur} chargement={chargement}>
          {null}
        </Chargement>
      </Page>
    );
  }

  const commande = donnees;
  const lignes = commande.lignes;
  const ouverte = ["commandee", "partiellement_recue"].includes(commande.statut);
  const bobines = lignes.find((l) => l.unite === "rouleau");

  const autres = lignes.filter((l) => l.unite !== "rouleau");
  const choisies = autres.filter((l) => inclus[l.id]);
  const lignesValides = choisies.every((l) => Number((quantites[l.id] ?? "").replace(",", ".")) > 0);
  const avecBobines = bobines ? inclus[bobines.id] : false;
  const pret = ouverte && (choisies.length > 0 || avecBobines) && lignesValides && (!avecBobines || packing !== null);

  async function enregistrer(e: FormEvent) {
    e.preventDefault();
    setEnvoi(true);
    setProblemes(null);
    try {
      const reception = await envoyer<S["ReceptionDetail"]>(`/api/commandes-achat/${id}/receptions`, {
        date_arrivee: dateArrivee,
        numero_facture: facture || null,
        commentaire: commentaire || null,
        import_colisage_id: avecBobines ? packing!.importId : null,
        lignes: [
          ...(avecBobines && bobines ? [{ ligne_commande_id: bobines.id }] : []),
          ...choisies.map((l) => ({ ligne_commande_id: l.id, quantite_recue: quantites[l.id].replace(",", ".") })),
        ],
      });
      aller(`/receptions/${reception.id}`);
    } catch (err) {
      setProblemes(messageErreur(err));
      setEnvoi(false);
    }
  }

  return (
    <Page
      titre={`Arrivée de marchandise — ${commande.numero}`}
      sousTitre="Rien n'entre en stock à cette étape : la marchandise sera contrôlée, puis seules les quantités conformes seront enregistrées."
      actions={<Link to={`/commandes/${id}`}>← Retour à la commande</Link>}
    >
      {!ouverte && <Alerte ton="alerte">Cette commande n'attend pas de marchandise.</Alerte>}
      <form className="formulaire" onSubmit={enregistrer}>
        <Carte titre="Livraison">
          <div className="rangee">
            <Champ etiquette="Date d'arrivée">
              <Saisie type="date" max={aujourdhui} value={dateArrivee} onChange={(e) => setDateArrivee(e.target.value)} />
            </Champ>
            <Champ etiquette="N° de facture ou bon de livraison">
              <Saisie value={facture} onChange={(e) => setFacture(e.target.value)} />
            </Champ>
          </div>
          <div style={{ marginTop: 14 }}>
            <Champ etiquette="Observation à l'arrivée (facultatif)">
              <Saisie value={commentaire} onChange={(e) => setCommentaire(e.target.value)} placeholder="ex. un carton visiblement mouillé" />
            </Champ>
          </div>
        </Carte>

        <Carte titre="Ce qui est arrivé">
          <div className="formulaire">
            {bobines && (
              <div>
                <label className="case">
                  <input
                    type="checkbox"
                    checked={!!inclus[bobines.id]}
                    onChange={(e) => {
                      setInclus({ ...inclus, [bobines.id]: e.target.checked });
                      if (!e.target.checked) setPacking(null);
                    }}
                  />
                  <span>
                    <strong>{bobines.article_code}</strong> — {bobines.article_nom} · reste {nombre(bobines.solde, 0)} à recevoir
                  </span>
                </label>
                {avecBobines && (
                  <div style={{ marginTop: 12, paddingLeft: 26 }}>
                    {packing ? (
                      <Alerte ton="ok">
                        Packing list du conteneur <strong>{packing.conteneur}</strong> analysée : <strong>{packing.nombre} bobines</strong>.{" "}
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
                        onAnnulee={() => setInclus({ ...inclus, [bobines.id]: false })}
                      />
                    )}
                  </div>
                )}
              </div>
            )}

            {autres.map((l) => (
              <div key={l.id} className="rangee" style={{ alignItems: "center" }}>
                <label className="case">
                  <input type="checkbox" checked={!!inclus[l.id]} onChange={(e) => setInclus({ ...inclus, [l.id]: e.target.checked })} />
                  <span>
                    <strong>{l.article_code}</strong> — {l.article_nom}
                    <div className="champ-aide">
                      Commandé {nombre(l.quantite_commandee, 1)} · reste {nombre(l.solde, 1)} {l.unite}
                    </div>
                  </span>
                </label>
                {inclus[l.id] && (
                  <Champ etiquette={`Quantité reçue (${l.unite})`}>
                    <Saisie inputMode="decimal" value={quantites[l.id] ?? ""} onChange={(e) => setQuantites({ ...quantites, [l.id]: e.target.value })} />
                  </Champ>
                )}
              </div>
            ))}
          </div>
        </Carte>

        {problemes && <Alerte>{problemes}</Alerte>}
        <div className="actions">
          <Bouton type="submit" chargement={envoi} disabled={!pret}>
            Enregistrer l'arrivée et passer au contrôle
          </Bouton>
        </div>
      </form>
    </Page>
  );
}
