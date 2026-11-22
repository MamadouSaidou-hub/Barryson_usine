import { Link, useNavigate } from "react-router-dom";
import { lire, requete, type S } from "../api";
import { useAuth } from "../auth";
import { ROLES } from "../libelles";
import { Bouton, Carte, Chargement, Page, nombre, useDonnees } from "../ui";

interface Tache {
  nombre: number;
  texte: string;
  vers: string;
  ton?: "alerte" | "danger";
}

// Accueil : ce que CETTE personne a a faire, en clair, un clic pour s'y rendre. Rien d'autre.
export function Tableau() {
  const { session, peut, peutUn } = useAuth();
  const aller = useNavigate();
  const utilisateur = session!.utilisateur;

  const { donnees, erreur, chargement } = useDonnees(async () => {
    const voitAchats = peut("achats.consulter");
    const voitProd = peut("production.consulter");
    const voitDR = peut("doctor_rewinder.consulter");
    const voitStock = peut("stock.consulter");
    const valideStock = peutUn("stock.valider_ajustement", "stock.valider_sortie_exceptionnelle", "stock.valider_entree_directe");
    const [aValider, aEnvoyer, aControler, attendues, ordres, dossiers, enAttente, soldes] = await Promise.all([
      peut("achats.valider") ? lire<S["CommandePublic"][]>("/api/commandes-achat" + requete({ statut: "soumise" })) : [],
      peut("achats.saisir") ? lire<S["CommandePublic"][]>("/api/commandes-achat" + requete({ statut: "validee" })) : [],
      voitAchats ? lire<S["ReceptionPublic"][]>("/api/receptions-achat" + requete({ statut: "en_controle" })) : [],
      voitAchats ? lire<S["CommandePublic"][]>("/api/commandes-achat" + requete({ en_attente_marchandise: true })) : [],
      voitProd ? lire<S["OrdrePublic"][]>("/api/ordres-fabrication") : [],
      voitDR ? lire<S["EncoursPublic"][]>("/api/doctor-rewinder") : [],
      voitStock && valideStock ? lire<S["MouvementPublic"][]>("/api/stock/mouvements" + requete({ statut: "en_attente" })) : [],
      voitStock ? lire<S["SoldeArticle"][]>("/api/stock/soldes") : [],
    ]);
    return { aValider, aEnvoyer, aControler, attendues, ordres, dossiers, enAttente, soldes };
  });

  function taches(d: NonNullable<typeof donnees>): Tache[] {
    const of = (statut: string) => d.ordres.filter((o) => o.statut === statut).length;
    const dr = (statut: string) => d.dossiers.filter((e) => e.statut === statut).length;
    const liste: (Tache | false)[] = [
      peut("achats.valider") && { nombre: d.aValider.length, texte: "commande(s) d'achat à valider", vers: "/commandes?statut=soumise", ton: "alerte" },
      peut("achats.saisir") && { nombre: d.aEnvoyer.length, texte: "commande(s) validée(s), à envoyer au fournisseur", vers: "/commandes?statut=validee" },
      peut("achats.consulter") && { nombre: d.aControler.length, texte: "arrivée(s) de marchandise à contrôler", vers: "/receptions", ton: "alerte" },
      peut("production.saisir") && { nombre: of("brouillon"), texte: "ordre(s) de fabrication à soumettre", vers: "/production?statut=brouillon" },
      peut("stock.executer_sortie") && { nombre: of("soumis"), texte: "ordre(s) : tubes à sortir du stock", vers: "/production?statut=soumis" },
      peut("production.saisir") && { nombre: of("matieres_validees"), texte: "ordre(s) prêt(s) à démarrer", vers: "/production?statut=matieres_validees" },
      peut("production.saisir") && { nombre: of("en_cours"), texte: "ordre(s) en fabrication : résultat à saisir", vers: "/production?statut=en_cours" },
      peut("production.valider") && { nombre: of("resultat_saisi"), texte: "résultat(s) de fabrication à valider", vers: "/production?statut=resultat_saisi", ton: "alerte" },
      peut("production.cloturer") && { nombre: of("resultat_valide"), texte: "ordre(s) à clôturer", vers: "/production?statut=resultat_valide" },
      peut("production.saisir") && { nombre: dr("en_cours"), texte: "dossier(s) Doctor Rewinder : retour à déclarer", vers: "/doctor-rewinder?statut=en_cours" },
      peut("doctor_rewinder.valider") && { nombre: dr("a_valider"), texte: "traitement(s) Doctor Rewinder à valider", vers: "/doctor-rewinder?statut=a_valider", ton: "alerte" },
      { nombre: d.enAttente.length, texte: "entrée(s) ou sortie(s) de stock à confirmer", vers: "/stock/mouvements?statut=en_attente", ton: "alerte" },
      { nombre: d.soldes.filter((s) => s.negatif).length, texte: "produit(s) avec un stock négatif (erreur à corriger)", vers: "/stock", ton: "danger" },
      { nombre: d.soldes.filter((s) => s.sous_seuil_min && !s.negatif).length, texte: "produit(s) presque fini(s)", vers: "/stock", ton: "alerte" },
    ];
    return liste.filter((t): t is Tache => t !== false && t.nombre > 0);
  }

  return (
    <Page titre={`Bonjour ${utilisateur.nom.split(" ")[0]}`} sousTitre={ROLES[utilisateur.role] ?? utilisateur.role}>
      <Chargement erreur={erreur} chargement={chargement}>
        {donnees && (
          <>
            <Carte titre="À faire">
              {(() => {
                const liste = taches(donnees);
                if (liste.length === 0) return <p className="vide">Rien à faire pour le moment. ✓</p>;
                return (
                  <ul className="taches">
                    {liste.map((t) => (
                      <li key={t.texte}>
                        <Link to={t.vers} className={`tache${t.ton ? ` tache-${t.ton}` : ""}`}>
                          <span className="tache-nombre">{nombre(t.nombre)}</span>
                          <span className="tache-texte">{t.texte}</span>
                          <span className="tache-fleche">→</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                );
              })()}
            </Carte>

            <div className="actions">
              {peut("achats.saisir") && <Bouton onClick={() => aller("/commandes/nouvelle")}>Nouvelle commande</Bouton>}
              {peut("stock.saisir") && (
                <Bouton variante="secondaire" onClick={() => aller("/stock")}>
                  Entrée ou sortie de stock
                </Bouton>
              )}
              {peut("production.saisir") && (
                <Bouton variante="secondaire" onClick={() => aller("/production/nouveau")}>
                  Nouvel ordre de fabrication
                </Bouton>
              )}
            </div>

            {donnees.attendues.length > 0 && (
              <p className="champ-aide">
                {nombre(donnees.attendues.length)} commande(s) en route vers l'usine : <Link to="/commandes?attente=1">les voir</Link>.
              </p>
            )}
          </>
        )}
      </Chargement>
    </Page>
  );
}
