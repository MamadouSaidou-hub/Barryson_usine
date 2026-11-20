import { useNavigate, useSearchParams } from "react-router-dom";
import { lire, requete, type S } from "../api";
import { useAuth } from "../auth";
import { STATUTS_COMMANDE } from "../libelles";
import { Badge, Bouton, Carte, Chargement, Choix, Page, Tableau, Vide, date, useAnnuaire, useDonnees } from "../ui";

export function Commandes() {
  const { peut } = useAuth();
  const aller = useNavigate();
  const nom = useAnnuaire();
  const [params, setParams] = useSearchParams();
  const statut = params.get("statut") ?? "";
  const attente = params.get("attente") === "1";

  const { donnees, erreur, chargement } = useDonnees(async () => {
    const [commandes, fournisseurs] = await Promise.all([
      lire<S["CommandePublic"][]>(
        "/api/commandes-achat" + requete({ statut: attente ? undefined : statut, en_attente_marchandise: attente || undefined }),
      ),
      lire<S["FournisseurPublic"][]>("/api/fournisseurs"),
    ]);
    return { commandes, fournisseurs: Object.fromEntries(fournisseurs.map((f) => [f.id, f.nom])) };
  }, [statut, attente]);

  return (
    <Page
      titre="Commandes d'achat"
      sousTitre="De la préparation de la commande au fournisseur jusqu'à la réception de la marchandise."
      actions={
        peut("achats.saisir") && <Bouton onClick={() => aller("/commandes/nouvelle")}>Préparer une commande</Bouton>
      }
    >
      <Carte>
        <div className="actions" style={{ marginBottom: 12 }}>
          <Choix
            aria-label="Filtrer par état"
            style={{ width: 260 }}
            value={attente ? "attente" : statut}
            onChange={(e) => {
              const v = e.target.value;
              setParams(v === "attente" ? { attente: "1" } : v ? { statut: v } : {});
            }}
          >
            <option value="">Toutes les commandes</option>
            <option value="attente">Marchandise attendue</option>
            {Object.entries(STATUTS_COMMANDE).map(([cle, { libelle }]) => (
              <option key={cle} value={cle}>
                {libelle}
              </option>
            ))}
          </Choix>
        </div>
        <Chargement erreur={erreur} chargement={chargement}>
          {donnees && donnees.commandes.length === 0 ? (
            <Vide>Aucune commande.</Vide>
          ) : (
            <Tableau colonnes={["N°", "Fournisseur", "État", "Devise", "Arrivée prévue", "Préparée par"]}>
              {donnees?.commandes.map((c) => (
                <tr key={c.id} className="cliquable" onClick={() => aller(`/commandes/${c.id}`)}>
                  <td className="mono">{c.numero}</td>
                  <td>{donnees.fournisseurs[c.fournisseur_id] ?? "—"}</td>
                  <td>
                    <Badge ton={STATUTS_COMMANDE[c.statut]?.ton}>{STATUTS_COMMANDE[c.statut]?.libelle}</Badge>
                  </td>
                  <td>{c.devise}</td>
                  <td>{date(c.date_arrivee_prevue)}</td>
                  <td>{nom(c.cree_par)}</td>
                </tr>
              ))}
            </Tableau>
          )}
        </Chargement>
      </Carte>
    </Page>
  );
}
