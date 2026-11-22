import { useState } from "react";
import { Link } from "react-router-dom";
import { lire, type S } from "../api";
import { useAuth } from "../auth";
import { Badge, Bouton, Carte, Chargement, Page, Tableau, Vide, nombre, useDonnees } from "../ui";
import { StockSaisie, type Sens } from "./StockSaisie";

export function Stock() {
  const { peut, session } = useAuth();
  const [saisie, setSaisie] = useState<Sens | null>(null);
  const [fait, setFait] = useState(false);
  const { donnees, erreur, chargement, recharger } = useDonnees(async () => {
    const [soldes, articles] = await Promise.all([
      lire<S["SoldeArticle"][]>("/api/stock/soldes"),
      peut("stock.saisir") ? lire<S["ArticlePublic"][]>("/api/articles?actif=true") : Promise.resolve([]),
    ]);
    return { soldes, articles };
  });

  return (
    <Page
      titre="Stock"
      sousTitre="Ce qu'il y a en magasin."
      actions={
        peut("stock.saisir") && (
          <>
            <Bouton onClick={() => { setFait(false); setSaisie("entree"); }}>+ Entrée</Bouton>
            <Bouton variante="secondaire" onClick={() => { setFait(false); setSaisie("sortie"); }}>− Sortie</Bouton>
          </>
        )
      }
    >
      {fait && (
        <div style={{ marginBottom: 12 }}>
          <Badge ton="ok">{session?.validations_actives === false ? "Enregistré. Le stock est à jour." : "Enregistré. Le stock sera à jour dès la confirmation."}</Badge>
        </div>
      )}
      <Carte>
        <Chargement erreur={erreur} chargement={chargement}>
          {donnees && donnees.soldes.length === 0 ? (
            <Vide>Aucun produit en stock.</Vide>
          ) : (
            <Tableau colonnes={["Produit", { texte: "En stock", droite: true }, ""]}>
              {donnees?.soldes.map((s) => (
                <tr key={s.article_id} className={s.negatif || s.sous_seuil_min ? "attention" : ""}>
                  <td>
                    <strong>{s.nom}</strong>
                    <div className="champ-aide">{s.code}</div>
                  </td>
                  <td className="droite">
                    <strong>{nombre(s.physique, 1)}</strong> {s.unite}
                    {s.reserve > 0 && <div className="champ-aide">dont {nombre(s.reserve, 1)} déjà promis</div>}
                  </td>
                  <td>
                    {s.negatif && <Badge ton="danger">Erreur : stock négatif</Badge>}{" "}
                    {s.sous_seuil_min && <Badge ton="alerte">Presque fini</Badge>}{" "}
                    {s.en_attente_validation > 0 && <Badge ton="info">{s.en_attente_validation} à confirmer</Badge>}
                  </td>
                </tr>
              ))}
            </Tableau>
          )}
        </Chargement>
        <p className="champ-aide" style={{ marginBottom: 0 }}>
          <Link to="/stock/mouvements">Voir ce qui est entré et sorti</Link> · <Link to="/stock/lots">Voir les bobines</Link>
        </p>
      </Carte>

      {saisie && donnees && (
        <StockSaisie
          sens={saisie}
          articles={donnees.articles}
          confirmation={session?.validations_actives !== false}
          onFermer={() => setSaisie(null)}
          onFait={() => {
            setSaisie(null);
            setFait(true);
            recharger();
          }}
        />
      )}
    </Page>
  );
}
