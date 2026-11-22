import { useState, type FormEvent } from "react";
import { envoyer, lire, modifier, type S } from "../api";
import { useAuth } from "../auth";
import { DEVISES, FINITIONS } from "../libelles";
import { Alerte, Badge, Bouton, Carte, Champ, Chargement, Choix, Page, Saisie, Tableau, Vide, messageErreur, nombre, useDonnees } from "../ui";

type Entree = S["CataloguePublic"];

const versNombre = (valeur: string) => (valeur.trim() === "" ? null : valeur.trim().replace(",", "."));

function Formulaire({ fournisseurId, articles, entree, onFermer, onEnregistre }: {
  fournisseurId: string;
  articles: S["ArticlePublic"][];
  entree: Entree | null;
  onFermer: () => void;
  onEnregistre: () => void;
}) {
  const edition = entree !== null;
  const [articleId, setArticleId] = useState(entree?.article_id ?? "");
  const [code, setCode] = useState(entree?.code ?? "");
  const [libelle, setLibelle] = useState(entree?.libelle ?? "");
  const [finition, setFinition] = useState(entree?.couleur_finition ?? "");
  const [reference, setReference] = useState(entree?.reference_couleur_fournisseur ?? "");
  const [poids, setPoids] = useState(entree?.poids_net_type_kg?.toString() ?? "");
  const [metrage, setMetrage] = useState(entree?.metrage_type_m?.toString() ?? "");
  const [prix, setPrix] = useState(entree?.prix_unitaire?.toString() ?? "");
  const [devisePrix, setDevisePrix] = useState(entree?.devise_prix ?? "USD");
  const [note, setNote] = useState(entree?.note ?? "");
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  const article = articles.find((a) => a.id === articleId);
  const estBobine = article?.unite_gestion === "rouleau";

  async function soumettre(e: FormEvent) {
    e.preventDefault();
    setEnvoi(true);
    setErreur(null);
    const caracteristiques = {
      libelle,
      couleur_finition: estBobine && finition ? finition : null,
      reference_couleur_fournisseur: reference.trim() || null,
      poids_net_type_kg: versNombre(poids),
      metrage_type_m: versNombre(metrage),
      prix_unitaire: versNombre(prix),
      devise_prix: versNombre(prix) === null ? null : devisePrix,
      note: note.trim() || null,
    };
    try {
      if (edition) await modifier(`/api/catalogue-fournisseur/${entree.id}`, caracteristiques);
      else await envoyer("/api/catalogue-fournisseur", { fournisseur_id: fournisseurId, article_id: articleId, code, ...caracteristiques });
      onEnregistre();
    } catch (err) {
      setErreur(messageErreur(err));
      setEnvoi(false);
    }
  }

  return (
    <div className="voile" role="dialog" aria-modal="true">
      <form className="modale" onSubmit={soumettre}>
        <h2>{edition ? "Modifier le produit" : "Nouveau produit au catalogue"}</h2>
        <Champ etiquette="Article en stock" aide={edition ? "Ne change pas : créez un autre produit si besoin." : "Ce que l'on recevra dans le stock."}>
          <Choix value={articleId} disabled={edition} onChange={(e) => setArticleId(e.target.value)}>
            <option value="">— Choisir —</option>
            {articles.map((a) => (
              <option key={a.id} value={a.id}>
                {a.code} — {a.nom}
              </option>
            ))}
          </Choix>
        </Champ>
        <div className="rangee">
          <Champ etiquette="Code" aide="Lettres, chiffres, tirets. Ne change jamais.">
            <Saisie value={code} disabled={edition} placeholder="ex. JUMBO-OR-GOLDEN01" onChange={(e) => setCode(e.target.value.toUpperCase())} />
          </Champ>
          <Champ etiquette="Libellé" aide="Ce que l'on lit sur la commande.">
            <Saisie value={libelle} placeholder="ex. Bobine BOPP or transparent — Golden01" onChange={(e) => setLibelle(e.target.value)} />
          </Champ>
        </div>
        {estBobine && (
          <div className="rangee">
            <Champ etiquette="Finition">
              <Choix value={finition} onChange={(e) => setFinition(e.target.value)}>
                <option value="">— Aucune —</option>
                {Object.entries(FINITIONS).map(([cle, texte]) => (
                  <option key={cle} value={cle}>
                    {texte}
                  </option>
                ))}
              </Choix>
            </Champ>
            <Champ etiquette="Référence couleur du fournisseur" aide="Le nom qu'il utilise (Golden01, Brown…).">
              <Saisie value={reference} onChange={(e) => setReference(e.target.value)} />
            </Champ>
          </div>
        )}
        <div className="rangee">
          <Champ etiquette="Poids net type (kg)" aide="Par bobine, facultatif.">
            <Saisie inputMode="decimal" value={poids} onChange={(e) => setPoids(e.target.value)} />
          </Champ>
          <Champ etiquette="Métrage type (m)" aide="Par bobine, facultatif.">
            <Saisie inputMode="decimal" value={metrage} onChange={(e) => setMetrage(e.target.value)} />
          </Champ>
        </div>
        <div className="rangee">
          <Champ etiquette="Prix habituel" aide="Facultatif. Proposé à la commande, toujours modifiable.">
            <Saisie inputMode="decimal" value={prix} onChange={(e) => setPrix(e.target.value)} />
          </Champ>
          <Champ etiquette="Devise du prix">
            <Choix value={devisePrix} onChange={(e) => setDevisePrix(e.target.value)}>
              {DEVISES.map((d) => (
                <option key={d}>{d}</option>
              ))}
            </Choix>
          </Champ>
        </div>
        <Champ etiquette="Note">
          <Saisie value={note} onChange={(e) => setNote(e.target.value)} />
        </Champ>
        {erreur && <Alerte>{erreur}</Alerte>}
        <div className="actions">
          <Bouton type="submit" chargement={envoi} disabled={!articleId || !libelle.trim() || (!edition && !code.trim())}>
            Enregistrer
          </Bouton>
          <Bouton type="button" variante="secondaire" onClick={onFermer}>
            Annuler
          </Bouton>
        </div>
      </form>
    </div>
  );
}

export function Catalogue() {
  const { peut } = useAuth();
  const { donnees, erreur, chargement, recharger } = useDonnees(async () => {
    const [fournisseurs, articles, catalogue] = await Promise.all([
      lire<S["FournisseurPublic"][]>("/api/fournisseurs?actif=true"),
      lire<S["ArticlePublic"][]>("/api/articles?actif=true"),
      lire<Entree[]>("/api/catalogue-fournisseur"),
    ]);
    return { fournisseurs, articles: articles.filter((a) => a.niveau_stock !== "produit_fini"), catalogue };
  });

  const [choix, setChoix] = useState("");
  const [desactives, setDesactives] = useState(false);
  const [formulaire, setFormulaire] = useState<{ entree: Entree | null } | null>(null);
  const [probleme, setProbleme] = useState<string | null>(null);

  const saisie = peut("achats.saisir");
  const fournisseurId = choix || donnees?.fournisseurs[0]?.id || "";
  const produits = (donnees?.catalogue ?? []).filter((e) => e.fournisseur_id === fournisseurId && (desactives || e.actif));
  const nbDesactives = (donnees?.catalogue ?? []).filter((e) => e.fournisseur_id === fournisseurId && !e.actif).length;

  async function basculer(e: Entree) {
    setProbleme(null);
    try {
      await modifier(`/api/catalogue-fournisseur/${e.id}`, { actif: !e.actif });
      await recharger();
    } catch (err) {
      setProbleme(messageErreur(err));
    }
  }

  return (
    <Page
      titre="Catalogue fournisseur"
      sousTitre="Les produits que l'on commande à chaque fournisseur, avec leurs caractéristiques. Ils se cochent ensuite en un clic quand on prépare une commande."
      actions={
        saisie && fournisseurId ? <Bouton onClick={() => setFormulaire({ entree: null })}>+ Nouveau produit</Bouton> : undefined
      }
    >
      <Chargement erreur={erreur} chargement={chargement}>
        {donnees && (
          <>
            <Carte>
              <div className="rangee">
                <Champ etiquette="Fournisseur">
                  <Choix value={fournisseurId} onChange={(e) => setChoix(e.target.value)}>
                    {donnees.fournisseurs.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.nom}
                      </option>
                    ))}
                  </Choix>
                </Champ>
                {nbDesactives > 0 && (
                  <label className="case" style={{ alignSelf: "end" }}>
                    <input type="checkbox" checked={desactives} onChange={(e) => setDesactives(e.target.checked)} />
                    <span>Afficher les {nbDesactives} produit(s) désactivé(s)</span>
                  </label>
                )}
              </div>
            </Carte>

            {probleme && <Alerte>{probleme}</Alerte>}
            <Carte titre="Produits">
              {produits.length === 0 ? (
                <Vide>Aucun produit au catalogue de ce fournisseur{saisie ? " : ajoutez le premier avec « + Nouveau produit »." : "."}</Vide>
              ) : (
                <Tableau colonnes={["Produit", "Finition", { texte: "Par bobine (environ)", droite: true }, "État", ""]}>
                  {produits.map((e) => (
                    <tr key={e.id} style={e.actif ? undefined : { opacity: 0.55 }}>
                      <td>
                        <strong>{e.libelle}</strong>
                        <div className="champ-aide">
                          {e.code} · {e.article_code}
                          {e.reference_couleur_fournisseur && <> · réf. fournisseur « {e.reference_couleur_fournisseur} »</>}
                        </div>
                        {e.note && <div className="champ-aide">{e.note}</div>}
                      </td>
                      <td>{e.couleur_finition ? FINITIONS[e.couleur_finition] : "—"}</td>
                      <td className="droite">
                        {e.poids_net_type_kg ? `${nombre(e.poids_net_type_kg, 0)} kg` : "—"}
                        {e.metrage_type_m ? ` · ${nombre(e.metrage_type_m, 0)} m` : ""}
                        {e.prix_unitaire !== null && <div>{nombre(e.prix_unitaire, 2)} {e.devise_prix}</div>}
                      </td>
                      <td>
                        <Badge ton={e.actif ? "ok" : "neutre"}>{e.actif ? "Actif" : "Désactivé"}</Badge>
                      </td>
                      <td className="droite" style={{ whiteSpace: "nowrap" }}>
                        {saisie && (
                          <>
                            <Bouton variante="lien" onClick={() => setFormulaire({ entree: e })}>
                              Modifier
                            </Bouton>{" "}
                            <Bouton variante="lien" onClick={() => basculer(e)}>
                              {e.actif ? "Désactiver" : "Réactiver"}
                            </Bouton>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </Tableau>
              )}
            </Carte>
          </>
        )}
      </Chargement>

      {formulaire && donnees && (
        <Formulaire
          fournisseurId={fournisseurId}
          articles={donnees.articles}
          entree={formulaire.entree}
          onFermer={() => setFormulaire(null)}
          onEnregistre={() => {
            setFormulaire(null);
            void recharger();
          }}
        />
      )}
    </Page>
  );
}
