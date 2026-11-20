import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { envoyer, lire, type S } from "../api";
import { DEVISES, FINITIONS } from "../libelles";
import { Alerte, Bouton, Carte, Champ, Chargement, Choix, Page, Saisie, Tableau, messageErreur, montant, useDonnees } from "../ui";

interface Ligne {
  article_id: string;
  quantite: string;
  prix: string;
  finition: string;
}

const LIGNE_VIDE: Ligne = { article_id: "", quantite: "", prix: "", finition: "" };

export function CommandeNouvelle() {
  const aller = useNavigate();
  const { donnees, erreur, chargement } = useDonnees(async () => {
    const [articles, fournisseurs] = await Promise.all([
      lire<S["ArticlePublic"][]>("/api/articles?actif=true"),
      lire<S["FournisseurPublic"][]>("/api/fournisseurs?actif=true"),
    ]);
    return { articles: articles.filter((a) => a.niveau_stock !== "produit_fini"), fournisseurs };
  });

  const [fournisseur, setFournisseur] = useState("");
  const [devise, setDevise] = useState<(typeof DEVISES)[number]>("USD");
  const [taux, setTaux] = useState("");
  const [arrivee, setArrivee] = useState("");
  const [reference, setReference] = useState("");
  const [commentaire, setCommentaire] = useState("");
  const [lignes, setLignes] = useState<Ligne[]>([{ ...LIGNE_VIDE }]);
  const [problemes, setProblemes] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  const article = (id: string) => donnees?.articles.find((a) => a.id === id);
  const total = lignes.reduce((somme, l) => somme + (Number(l.quantite) || 0) * (Number(l.prix.replace(",", ".")) || 0), 0);
  const prixManquants = lignes.some((l) => l.article_id && !l.prix);
  const tauxNombre = Number(taux.replace(",", "."));

  function changer(i: number, champ: keyof Ligne, valeur: string) {
    setLignes((anciennes) =>
      anciennes.map((l, j) => (j === i ? { ...l, [champ]: valeur, ...(champ === "article_id" ? { finition: "" } : {}) } : l)),
    );
  }

  async function enregistrer(e: FormEvent) {
    e.preventDefault();
    setEnvoi(true);
    setProblemes(null);
    try {
      const commande = await envoyer<S["CommandeDetail"]>("/api/commandes-achat", {
        fournisseur_id: fournisseur,
        devise,
        taux_change_gnf: devise !== "GNF" && taux ? taux.replace(",", ".") : null,
        date_arrivee_prevue: arrivee || null,
        reference_fournisseur: reference || null,
        commentaire: commentaire || null,
        lignes: lignes
          .filter((l) => l.article_id)
          .map((l) => ({
            article_id: l.article_id,
            quantite_commandee: l.quantite.replace(",", "."),
            prix_unitaire: l.prix ? l.prix.replace(",", ".") : null,
            couleur_finition: l.finition || null,
          })),
      });
      aller(`/commandes/${commande.id}`);
    } catch (err) {
      setProblemes(messageErreur(err));
      setEnvoi(false);
    }
  }

  const valide = fournisseur && lignes.some((l) => l.article_id && Number(l.quantite.replace(",", ".")) > 0);

  return (
    <Page titre="Préparer une commande d'achat" sousTitre="La commande restera en brouillon jusqu'à ce que vous la soumettiez au Directeur général.">
      <Chargement erreur={erreur} chargement={chargement}>
        {donnees && (
          <form className="formulaire" onSubmit={enregistrer}>
            <Carte titre="Fournisseur et conditions">
              <div className="formulaire">
                <div className="rangee">
                  <Champ etiquette="Fournisseur">
                    <Choix value={fournisseur} onChange={(e) => setFournisseur(e.target.value)}>
                      <option value="">— Choisir —</option>
                      {donnees.fournisseurs.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.nom}
                        </option>
                      ))}
                    </Choix>
                  </Champ>
                  <Champ etiquette="Devise de la commande">
                    <Choix value={devise} onChange={(e) => setDevise(e.target.value as typeof devise)}>
                      {DEVISES.map((d) => (
                        <option key={d}>{d}</option>
                      ))}
                    </Choix>
                  </Champ>
                  {devise !== "GNF" && (
                    <Champ etiquette={`Taux du jour (1 ${devise} = … GNF)`} aide="Facultatif. Sert à estimer le montant en GNF pour le DG.">
                      <Saisie inputMode="decimal" value={taux} placeholder="ex. 8650" onChange={(e) => setTaux(e.target.value)} />
                    </Champ>
                  )}
                </div>
                <div className="rangee">
                  <Champ etiquette="Arrivée prévue">
                    <Saisie type="date" value={arrivee} onChange={(e) => setArrivee(e.target.value)} />
                  </Champ>
                  <Champ etiquette="Référence du fournisseur" aide="Numéro de proforma ou de bon de commande.">
                    <Saisie value={reference} onChange={(e) => setReference(e.target.value)} />
                  </Champ>
                </div>
                <Champ etiquette="Commentaire">
                  <Saisie value={commentaire} onChange={(e) => setCommentaire(e.target.value)} />
                </Champ>
              </div>
            </Carte>

            <Carte
              titre="Lignes de la commande"
              droite={
                <Bouton type="button" variante="secondaire" onClick={() => setLignes([...lignes, { ...LIGNE_VIDE }])}>
                  + Ajouter une ligne
                </Bouton>
              }
            >
              <Tableau colonnes={["Article", "Finition (bobines)", { texte: "Quantité", droite: true }, { texte: `Prix unitaire (${devise})`, droite: true }, { texte: "Montant", droite: true }, ""]}>
                {lignes.map((l, i) => {
                  const a = article(l.article_id);
                  return (
                    <tr key={i}>
                      <td style={{ minWidth: 230 }}>
                        <Choix aria-label="Article" value={l.article_id} onChange={(e) => changer(i, "article_id", e.target.value)}>
                          <option value="">— Choisir —</option>
                          {donnees.articles.map((x) => (
                            <option key={x.id} value={x.id}>
                              {x.code} — {x.nom}
                            </option>
                          ))}
                        </Choix>
                      </td>
                      <td style={{ minWidth: 170 }}>
                        {a?.unite_gestion === "rouleau" ? (
                          <Choix aria-label="Finition" value={l.finition} onChange={(e) => changer(i, "finition", e.target.value)}>
                            <option value="">Toutes</option>
                            {Object.entries(FINITIONS).map(([cle, libelle]) => (
                              <option key={cle} value={cle}>
                                {libelle}
                              </option>
                            ))}
                          </Choix>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td style={{ width: 150 }}>
                        <Saisie aria-label="Quantité" className="saisie droite" inputMode="decimal" value={l.quantite} onChange={(e) => changer(i, "quantite", e.target.value)} />
                        {a && <small className="champ-aide">en {a.unite_gestion}</small>}
                      </td>
                      <td style={{ width: 170 }}>
                        <Saisie aria-label="Prix unitaire" className="saisie droite" inputMode="decimal" value={l.prix} onChange={(e) => changer(i, "prix", e.target.value)} />
                      </td>
                      <td className="droite mono">
                        {l.prix && l.quantite ? montant((Number(l.quantite.replace(",", ".")) || 0) * (Number(l.prix.replace(",", ".")) || 0), devise) : "—"}
                      </td>
                      <td>
                        {lignes.length > 1 && (
                          <Bouton type="button" variante="lien" onClick={() => setLignes(lignes.filter((_, j) => j !== i))}>
                            Retirer
                          </Bouton>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </Tableau>
              <p className="droite" style={{ marginBottom: 0 }}>
                <strong>Total : {montant(total, devise)}</strong>
                {devise !== "GNF" && tauxNombre > 0 && <> ≈ {montant(total * tauxNombre, "GNF")}</>}
              </p>
              {prixManquants && <p className="champ-aide droite">Certains prix ne sont pas renseignés : le total est partiel.</p>}
            </Carte>

            {problemes && <Alerte>{problemes}</Alerte>}
            <div className="actions">
              <Bouton type="submit" chargement={envoi} disabled={!valide}>
                Enregistrer le brouillon
              </Bouton>
              <Bouton type="button" variante="secondaire" onClick={() => aller("/commandes")}>
                Annuler
              </Bouton>
            </div>
          </form>
        )}
      </Chargement>
    </Page>
  );
}
