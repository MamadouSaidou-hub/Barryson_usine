import { useNavigate, useSearchParams } from "react-router-dom";
import { lire, requete, type S } from "../api";
import { useAuth } from "../auth";
import { STATUTS_OF } from "../libelles";
import { Badge, Bouton, Carte, Chargement, Choix, Page, Tableau, Vide, dateHeure, nombre, useAnnuaire, useDonnees } from "../ui";

export function Production() {
  const { peut } = useAuth();
  const aller = useNavigate();
  const nom = useAnnuaire();
  const [params, setParams] = useSearchParams();
  const statut = params.get("statut") ?? "";

  const { donnees, erreur, chargement } = useDonnees(async () => {
    const [ordres, modeles] = await Promise.all([
      lire<S["OrdrePublic"][]>("/api/ordres-fabrication" + requete({ statut })),
      lire<S["ModelePublic"][]>("/api/modeles-ruban"),
    ]);
    return { ordres, modeles: Object.fromEntries(modeles.map((m) => [m.id, m.nom])) };
  }, [statut]);

  return (
    <Page
      titre="Ordres de fabrication"
      sousTitre="Chaque ordre découpe une bobine en rouleaux, de la sortie des tubes jusqu'à l'entrée des produits finis en stock."
      actions={peut("production.saisir") && <Bouton onClick={() => aller("/production/nouveau")}>Préparer un ordre</Bouton>}
    >
      <Carte>
        <div className="actions" style={{ marginBottom: 12 }}>
          <Choix
            aria-label="Filtrer par état"
            style={{ width: 260 }}
            value={statut}
            onChange={(e) => setParams(e.target.value ? { statut: e.target.value } : {})}
          >
            <option value="">Tous les ordres</option>
            {Object.entries(STATUTS_OF).map(([cle, { libelle }]) => (
              <option key={cle} value={cle}>
                {libelle}
              </option>
            ))}
          </Choix>
        </div>
        <Chargement erreur={erreur} chargement={chargement}>
          {donnees && donnees.ordres.length === 0 ? (
            <Vide>Aucun ordre de fabrication.</Vide>
          ) : (
            <Tableau colonnes={["N°", "Modèle", { texte: "Métrage engagé", droite: true }, { texte: "Pièces prévues", droite: true }, "État", "Préparé par"]}>
              {donnees?.ordres.map((o) => (
                <tr key={o.id} className="cliquable" onClick={() => aller(`/production/${o.id}`)}>
                  <td className="mono">{o.numero}</td>
                  <td>{donnees.modeles[o.modele_id] ?? "—"}</td>
                  <td className="droite">{nombre(o.metrage_engage, 0)} m</td>
                  <td className="droite">{o.pieces_theoriques === null ? "—" : nombre(o.pieces_theoriques)}</td>
                  <td>
                    <Badge ton={STATUTS_OF[o.statut]?.ton}>{STATUTS_OF[o.statut]?.libelle}</Badge>
                    {o.alertes.length > 0 && <> <Badge ton="alerte">{o.alertes.length} alerte(s)</Badge></>}
                  </td>
                  <td>
                    {nom(o.cree_par)}
                    <div className="champ-aide">{dateHeure(o.cree_le)}</div>
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
