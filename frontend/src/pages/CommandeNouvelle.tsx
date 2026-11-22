import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { envoyer, lire, type S } from "../api";
import { useAuth } from "../auth";
import { DEVISES, FINITIONS } from "../libelles";
import { Alerte, Badge, Bouton, Carte, Champ, Chargement, Choix, Page, Saisie, Tableau, messageErreur, montant, nombre, useDonnees } from "../ui";

interface Ligne {
  article_id: string;
  quantite: string;
  prix: string;
  finition: string;
  // Renseigne quand la ligne vient du catalogue du fournisseur : article et finition sont alors imposes.
  catalogue_id?: string;
  // Vrai tant que le prix affiche vient du catalogue et n'a pas ete retouche.
  prixAuto?: boolean;
}

const LIGNE_VIDE: Ligne = { article_id: "", quantite: "", prix: "", finition: "" };

export function CommandeNouvelle() {
  const aller = useNavigate();
  const { session } = useAuth();
  const sansCircuit = session?.validations_actives === false;
  const { donnees, erreur, chargement } = useDonnees(async () => {
    const [articles, fournisseurs, catalogue] = await Promise.all([
      lire<S["ArticlePublic"][]>("/api/articles?actif=true"),
      lire<S["FournisseurPublic"][]>("/api/fournisseurs?actif=true"),
      lire<S["CataloguePublic"][]>("/api/catalogue-fournisseur?actif=true"),
    ]);
    return { articles: articles.filter((a) => a.niveau_stock !== "produit_fini"), fournisseurs, catalogue };
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

  const produitsDuFournisseur = donnees?.catalogue.filter((e) => e.fournisseur_id === fournisseur) ?? [];
  const catalogueParId = (id?: string) => donnees?.catalogue.find((e) => e.id === id);

  function choisirFournisseur(id: string) {
    setFournisseur(id);
    // Les produits d'un catalogue n'ont de sens que chez leur fournisseur : on garde seulement les lignes libres.
    setLignes((anciennes) => {
      const libres = anciennes.filter((l) => !l.catalogue_id);
      return libres.length > 0 ? libres : [{ ...LIGNE_VIDE }];
    });
  }

  // Le prix du catalogue n'est propose que dans sa devise : 1 450 USD ne devient jamais 1 450 EUR.
  const prixPropose = (e: S["CataloguePublic"] | undefined, deviseCommande: string) =>
    e && e.prix_unitaire !== null && e.devise_prix === deviseCommande ? String(e.prix_unitaire) : "";

  function changerDevise(nouvelle: (typeof DEVISES)[number]) {
    setDevise(nouvelle);
    // Les prix repris du catalogue suivent la devise ; ceux saisis a la main ne sont jamais touches.
    setLignes((anciennes) =>
      anciennes.map((l) => (l.catalogue_id && l.prixAuto ? { ...l, prix: prixPropose(catalogueParId(l.catalogue_id), nouvelle) } : l)),
    );
  }

  function ajouterDuCatalogue(e: S["CataloguePublic"]) {
    const prix = prixPropose(e, devise);
    const nouvelle: Ligne = { article_id: e.article_id, quantite: "", prix, prixAuto: true, finition: e.couleur_finition ?? "", catalogue_id: e.id };
    setLignes((anciennes) => {
      const vide = anciennes.length === 1 && !anciennes[0].article_id && !anciennes[0].quantite && !anciennes[0].prix;
      return vide ? [nouvelle] : [...anciennes, nouvelle];
    });
  }

  function changer(i: number, champ: keyof Ligne, valeur: string) {
    setLignes((anciennes) =>
      anciennes.map((l, j) => (j === i ? { ...l, [champ]: valeur, ...(champ === "article_id" ? { finition: "" } : {}), ...(champ === "prix" ? { prixAuto: false } : {}) } : l)),
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
            catalogue_id: l.catalogue_id ?? null,
          })),
      });
      // Sans circuit de validation (developpement), enregistrer = commander : plus d'etape entre les deux.
      if (sansCircuit) await envoyer(`/api/commandes-achat/${commande.id}/commander`);
      aller(`/commandes/${commande.id}`);
    } catch (err) {
      setProblemes(messageErreur(err));
      setEnvoi(false);
    }
  }

  const valide = fournisseur && lignes.some((l) => l.article_id && Number(l.quantite.replace(",", ".")) > 0);

  return (
    <Page titre="Nouvelle commande" sousTitre={sansCircuit ? "Choisissez le fournisseur, ajoutez les produits et les quantités." : "Choisissez le fournisseur, ajoutez les produits et les quantités. Le Directeur général validera."}>
      <Chargement erreur={erreur} chargement={chargement}>
        {donnees && (
          <form className="formulaire" onSubmit={enregistrer}>
            <Carte titre="Chez quel fournisseur ?">
              <div className="formulaire">
                <div className="rangee">
                  <Champ etiquette="Fournisseur">
                    <Choix value={fournisseur} onChange={(e) => choisirFournisseur(e.target.value)}>
                      <option value="">— Choisir —</option>
                      {donnees.fournisseurs.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.nom}
                        </option>
                      ))}
                    </Choix>
                  </Champ>
                  <Champ etiquette="Devise de la commande">
                    <Choix value={devise} onChange={(e) => changerDevise(e.target.value as typeof devise)}>
                      {DEVISES.map((d) => (
                        <option key={d}>{d}</option>
                      ))}
                    </Choix>
                  </Champ>
                </div>
                <details>
                  <summary>Plus d'options (taux, date d'arrivée, référence…)</summary>
                  <div className="formulaire" style={{ marginTop: 12 }}>
                    {devise !== "GNF" && (
                      <Champ etiquette={`Taux du jour (1 ${devise} = … GNF)`} aide="Facultatif. Sert à estimer le montant en GNF pour le DG.">
                        <Saisie inputMode="decimal" value={taux} placeholder="ex. 8650" onChange={(e) => setTaux(e.target.value)} />
                      </Champ>
                    )}
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
                </details>
              </div>
            </Carte>

            {fournisseur && (
              <Carte titre="Ses produits">
                {produitsDuFournisseur.length === 0 ? (
                  <p className="champ-aide" style={{ margin: 0 }}>
                    Aucun produit au catalogue de ce fournisseur : ajoutez des lignes libres ci-dessous.
                  </p>
                ) : (
                  <Tableau colonnes={["Produit", "Finition", { texte: "Par bobine (environ)", droite: true }, ""]}>
                    {produitsDuFournisseur.map((e) => {
                      const dejaAjoute = lignes.some((l) => l.catalogue_id === e.id);
                      return (
                        <tr key={e.id}>
                          <td>
                            <strong>{e.libelle}</strong>
                            {e.reference_couleur_fournisseur && (
                              <div className="champ-aide">Référence fournisseur : {e.reference_couleur_fournisseur}</div>
                            )}
                          </td>
                          <td>{e.couleur_finition ? <Badge>{FINITIONS[e.couleur_finition]}</Badge> : "—"}</td>
                          <td className="droite">
                            {e.poids_net_type_kg ? `${nombre(e.poids_net_type_kg, 0)} kg` : "—"}
                            {e.metrage_type_m ? ` · ${nombre(e.metrage_type_m, 0)} m` : ""}
                          </td>
                          <td className="droite">
                            <Bouton type="button" variante="secondaire" disabled={dejaAjoute} onClick={() => ajouterDuCatalogue(e)}>
                              {dejaAjoute ? "Ajouté ✓" : "Ajouter"}
                            </Bouton>
                          </td>
                        </tr>
                      );
                    })}
                  </Tableau>
                )}
              </Carte>
            )}

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
                  const produit = catalogueParId(l.catalogue_id);
                  return (
                    <tr key={i}>
                      <td style={{ minWidth: 230 }}>
                        {produit ? (
                          <>
                            <strong>{produit.libelle}</strong>
                            <div className="champ-aide">Du catalogue du fournisseur</div>
                          </>
                        ) : (
                          <Choix aria-label="Article" value={l.article_id} onChange={(e) => changer(i, "article_id", e.target.value)}>
                            <option value="">— Choisir —</option>
                            {donnees.articles.map((x) => (
                              <option key={x.id} value={x.id}>
                                {x.code} — {x.nom}
                              </option>
                            ))}
                          </Choix>
                        )}
                      </td>
                      <td style={{ minWidth: 170 }}>
                        {produit ? (
                          produit.couleur_finition ? FINITIONS[produit.couleur_finition] : "—"
                        ) : a?.unite_gestion === "rouleau" ? (
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
                Enregistrer la commande
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
