import { useNavigate, useSearchParams } from "react-router-dom";
import { lire, requete, type S } from "../api";
import { STATUTS_RECEPTION } from "../libelles";
import { Badge, Carte, Chargement, Choix, Page, Tableau, Vide, date, useAnnuaire, useDonnees } from "../ui";

export function Receptions() {
  const aller = useNavigate();
  const nom = useAnnuaire();
  const [params, setParams] = useSearchParams();
  const statut = params.get("statut") ?? "en_controle";
  const litiges = statut === "litiges";

  const { donnees, erreur, chargement } = useDonnees(
    () =>
      lire<S["ReceptionPublic"][]>(
        "/api/receptions-achat" + requete(litiges ? { avec_ecarts: true } : { statut: statut === "toutes" ? undefined : statut }),
      ),
    [statut],
  );

  return (
    <Page
      titre="Arrivées de marchandise"
      sousTitre="Chaque arrivée est contrôlée avant d'entrer en stock : seules les quantités acceptées sont enregistrées."
    >
      <Carte>
        <div className="actions" style={{ marginBottom: 12 }}>
          <Choix aria-label="Filtrer" style={{ width: 280 }} value={statut} onChange={(e) => setParams({ statut: e.target.value })}>
            <option value="en_controle">À contrôler</option>
            <option value="litiges">Litiges (réserves ou refus)</option>
            <option value="acceptee">Acceptées</option>
            <option value="toutes">Toutes</option>
          </Choix>
        </div>
        <Chargement erreur={erreur} chargement={chargement}>
          {donnees && donnees.length === 0 ? (
            <Vide>Aucune arrivée dans cette catégorie.</Vide>
          ) : (
            <Tableau colonnes={["Réception", "Conteneur", "Facture", "Arrivée", "État", "Contrôlée par"]}>
              {donnees?.map((r) => (
                <tr key={r.id} className="cliquable" onClick={() => aller(`/receptions/${r.id}`)}>
                  <td className="mono">{r.numero}</td>
                  <td>{r.conteneur_reference ?? "—"}</td>
                  <td>{r.numero_facture ?? "—"}</td>
                  <td>{date(r.date_arrivee)}</td>
                  <td>
                    <Badge ton={STATUTS_RECEPTION[r.statut]?.ton}>{STATUTS_RECEPTION[r.statut]?.libelle}</Badge>
                  </td>
                  <td>{r.controle_par ? nom(r.controle_par) : "—"}</td>
                </tr>
              ))}
            </Tableau>
          )}
        </Chargement>
      </Carte>
    </Page>
  );
}
