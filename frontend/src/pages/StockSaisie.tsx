import { useState, type FormEvent } from "react";
import { envoyer, type S } from "../api";
import { Alerte, Bouton, Champ, Choix, Saisie, messageErreur } from "../ui";

export type Sens = "entree" | "sortie";

// Raisons courantes : un choix dans une liste evite de taper du texte, "Autre" laisse la place a une precision.
const RAISONS: Record<Sens, string[]> = {
  entree: ["Production terminée", "Retour client", "Comptage : il y en a plus", "Autre"],
  sortie: ["Livraison client", "Casse ou perte", "Échantillon", "Comptage : il y en a moins", "Autre"],
};

// Entree ou sortie de stock en deux champs. Le type technique se deduit tout seul :
// entree d'un produit fini = entree directe, autre entree = ajustement ; toute sortie = sortie exceptionnelle.
export function StockSaisie({ sens, articles, confirmation, onFermer, onFait }: {
  sens: Sens;
  articles: S["ArticlePublic"][];
  // Vrai : une autre personne doit confirmer (circuit de validation actif). Faux : le stock bouge tout de suite.
  confirmation: boolean;
  onFermer: () => void;
  onFait: () => void;
}) {
  const [article, setArticle] = useState("");
  const [quantite, setQuantite] = useState("");
  const [raison, setRaison] = useState(RAISONS[sens][0]);
  const [precision, setPrecision] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  const choisi = articles.find((a) => a.id === article);
  const motif = raison === "Autre" ? precision.trim() : precision.trim() ? `${raison} — ${precision.trim()}` : raison;
  const valide = !!article && Number(quantite.replace(",", ".")) > 0 && motif.length >= 5;

  async function soumettre(e: FormEvent) {
    e.preventDefault();
    if (!choisi) return;
    setEnvoi(true);
    setErreur(null);
    try {
      const type = sens === "sortie" ? "sortie_exceptionnelle" : choisi.niveau_stock === "produit_fini" ? "entree_directe" : "ajustement";
      await envoyer("/api/stock/mouvements", {
        type,
        article_id: article,
        quantite: quantite.replace(",", "."),
        motif,
        ...(type === "ajustement" ? { sens: "plus" } : {}),
      });
      onFait();
    } catch (err) {
      setErreur(messageErreur(err));
      setEnvoi(false);
    }
  }

  return (
    <div className="voile" role="dialog" aria-modal="true">
      <form className="modale" onSubmit={soumettre}>
        <h2>{sens === "entree" ? "Entrée en stock" : "Sortie de stock"}</h2>
        <Champ etiquette="Quel produit ?">
          <Choix value={article} onChange={(e) => setArticle(e.target.value)} autoFocus>
            <option value="">— Choisir —</option>
            {articles.map((a) => (
              <option key={a.id} value={a.id}>
                {a.nom}
              </option>
            ))}
          </Choix>
        </Champ>
        <Champ etiquette={choisi ? `Combien ? (en ${choisi.unite_gestion})` : "Combien ?"}>
          <Saisie inputMode="decimal" value={quantite} onChange={(e) => setQuantite(e.target.value)} />
        </Champ>
        <Champ etiquette="Pourquoi ?">
          <Choix value={raison} onChange={(e) => setRaison(e.target.value)}>
            {RAISONS[sens].map((r) => (
              <option key={r}>{r}</option>
            ))}
          </Choix>
        </Champ>
        {(raison === "Autre" || precision) && (
          <Champ etiquette={raison === "Autre" ? "Précisez" : "Précision (facultatif)"}>
            <Saisie value={precision} onChange={(e) => setPrecision(e.target.value)} />
          </Champ>
        )}
        {raison !== "Autre" && !precision && (
          <Bouton type="button" variante="lien" onClick={() => setPrecision(" ")} style={{ alignSelf: "flex-start" }}>
            Ajouter une précision
          </Bouton>
        )}
        {confirmation && (
          <p className="champ-aide" style={{ margin: 0 }}>
            Le stock sera mis à jour dès qu'une autre personne aura confirmé.
          </p>
        )}
        {erreur && <Alerte>{erreur}</Alerte>}
        <div className="actions droite">
          <Bouton type="button" variante="secondaire" onClick={onFermer}>
            Annuler
          </Bouton>
          <Bouton type="submit" chargement={envoi} disabled={!valide}>
            Enregistrer
          </Bouton>
        </div>
      </form>
    </div>
  );
}
