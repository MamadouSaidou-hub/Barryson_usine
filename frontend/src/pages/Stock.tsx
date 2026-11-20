import { useState } from "react";
import { lire, requete, type S } from "../api";
import { NIVEAUX } from "../libelles";
import { Badge, Carte, Chargement, Choix, Page, Tableau, Vide, nombre, useDonnees } from "../ui";

export function Stock() {
  const [niveau, setNiveau] = useState("");
  const { donnees, erreur, chargement } = useDonnees(
    () => lire<S["SoldeArticle"][]>("/api/stock/soldes" + requete({ niveau })),
    [niveau],
  );

  return (
    <Page
      titre="Niveaux de stock"
      sousTitre="Le stock est la somme des mouvements validés. Le disponible est le physique moins ce qui est réservé."
    >
      <Carte>
        <div className="actions" style={{ marginBottom: 12 }}>
          <Choix aria-label="Niveau" style={{ width: 240 }} value={niveau} onChange={(e) => setNiveau(e.target.value)}>
            <option value="">Tous les niveaux</option>
            {Object.entries(NIVEAUX).map(([cle, libelle]) => (
              <option key={cle} value={cle}>
                {libelle}
              </option>
            ))}
          </Choix>
        </div>
        <Chargement erreur={erreur} chargement={chargement}>
          {donnees && donnees.length === 0 ? (
            <Vide>Aucun article.</Vide>
          ) : (
            <Tableau
              colonnes={[
                "Article",
                "Niveau",
                { texte: "En stock", droite: true },
                { texte: "Réservé", droite: true },
                { texte: "Disponible", droite: true },
                "Alertes",
              ]}
            >
              {donnees?.map((s) => (
                <tr key={s.article_id} className={s.negatif || s.sous_seuil_min ? "attention" : ""}>
                  <td>
                    <strong>{s.code}</strong>
                    <div className="champ-aide">{s.nom}</div>
                  </td>
                  <td>{NIVEAUX[s.niveau_stock]}</td>
                  <td className="droite">
                    {nombre(s.physique, 1)} {s.unite}
                  </td>
                  <td className="droite">{nombre(s.reserve, 1)}</td>
                  <td className="droite">
                    <strong>{nombre(s.disponible, 1)}</strong>
                  </td>
                  <td>
                    {s.negatif && <Badge ton="danger">Stock négatif</Badge>}{" "}
                    {s.sous_seuil_min && <Badge ton="alerte">Sous le seuil</Badge>}{" "}
                    {s.en_attente_validation > 0 && <Badge ton="info">{s.en_attente_validation} à valider</Badge>}
                  </td>
                </tr>
              ))}
            </Tableau>
          )}
        </Chargement>
      </Carte>
    </Page>
  );
}
