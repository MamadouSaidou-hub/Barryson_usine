import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import { ROLES } from "./libelles";
import { Arrivee } from "./pages/Arrivee";
import { DoctorRewinder } from "./pages/DoctorRewinder";
import { DoctorRewinderDetail } from "./pages/DoctorRewinderDetail";
import { Production } from "./pages/Production";
import { ProductionDetail } from "./pages/ProductionDetail";
import { ProductionNouveau } from "./pages/ProductionNouveau";
import { Catalogue } from "./pages/Catalogue";
import { ChangerMotDePasse, ConfigurerDoubleFacteur, Connexion } from "./pages/Acces";
import { CommandeDetail } from "./pages/CommandeDetail";
import { CommandeNouvelle } from "./pages/CommandeNouvelle";
import { Commandes } from "./pages/Commandes";
import { Controle } from "./pages/Controle";
import { Delegations } from "./pages/Delegations";
import { Lots } from "./pages/Lots";
import { Mouvements } from "./pages/Mouvements";
import { Receptions } from "./pages/Receptions";
import { Referentiel } from "./pages/Referentiel";
import { Stock } from "./pages/Stock";
import { Tableau } from "./pages/Tableau";
import { Alerte, Bouton } from "./ui";

interface Entree {
  vers: string;
  libelle: string;
  droit: string[];
  fin?: boolean;
}

const MENU: { groupe: string; entrees: Entree[] }[] = [
  {
    groupe: "",
    entrees: [
      { vers: "/", libelle: "Accueil", droit: [], fin: true },
      { vers: "/commandes", libelle: "Commander", droit: ["achats.consulter"] },
      { vers: "/receptions", libelle: "Recevoir", droit: ["achats.consulter"] },
      { vers: "/stock", libelle: "Stock", droit: ["stock.consulter"], fin: true },
      { vers: "/production", libelle: "Production", droit: ["production.consulter"] },
      { vers: "/doctor-rewinder", libelle: "Doctor Rewinder", droit: ["doctor_rewinder.consulter"] },
    ],
  },
  {
    groupe: "Réglages",
    entrees: [
      { vers: "/catalogue", libelle: "Produits du fournisseur", droit: ["achats.consulter"] },
      { vers: "/referentiel", libelle: "Articles et fournisseurs", droit: ["referentiels.consulter", "achats.consulter"] },
      { vers: "/delegations", libelle: "Délégations", droit: ["delegations.gerer"] },
    ],
  },
];

function Disposition() {
  const { session, peutUn, deconnecter } = useAuth();
  const utilisateur = session!.utilisateur;
  const deleguees = session!.permissions_deleguees;

  return (
    <div className="application">
      <nav className="menu" aria-label="Navigation principale">
        <div className="marque">
          Barryson ERP
          <small>Group BARRYSON Sarl</small>
        </div>
        {MENU.map(({ groupe, entrees }) => {
          const visibles = entrees.filter(
            (e) => (e.droit.length === 0 || peutUn(...e.droit)) && !(e.vers === "/delegations" && session!.validations_actives === false),
          );
          if (visibles.length === 0) return null;
          return (
            <div key={groupe} style={{ display: "contents" }}>
              {groupe && <div className="groupe">{groupe}</div>}
              {visibles.map((e) => (
                <NavLink key={e.vers} to={e.vers} end={e.fin} className={({ isActive }) => (isActive ? "actif" : "")}>
                  {e.libelle}
                </NavLink>
              ))}
            </div>
          );
        })}
        <div className="pied">
          <strong>{utilisateur.nom}</strong>
          <div>{ROLES[utilisateur.role] ?? utilisateur.role}</div>
          {deleguees.length > 0 && <div style={{ marginTop: 6 }}>✦ Délégation du DG en cours</div>}
          <Bouton variante="secondaire" onClick={deconnecter}>
            Se déconnecter
          </Bouton>
        </div>
      </nav>
      <main className="contenu">
        {deleguees.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <Alerte ton="info">
              Vous agissez avec une <strong>délégation du Directeur général</strong> : vos validations sont
              enregistrées à votre nom, avec la mention de la délégation.
            </Alerte>
          </div>
        )}
        <Routes>
          <Route path="/" element={<Tableau />} />
          <Route path="/commandes" element={<Commandes />} />
          <Route path="/commandes/nouvelle" element={<CommandeNouvelle />} />
          <Route path="/commandes/:id" element={<CommandeDetail />} />
          <Route path="/commandes/:id/arrivee" element={<Arrivee />} />
          <Route path="/catalogue" element={<Catalogue />} />
          <Route path="/receptions" element={<Receptions />} />
          <Route path="/receptions/:id" element={<Controle />} />
          <Route path="/production" element={<Production />} />
          <Route path="/production/nouveau" element={<ProductionNouveau />} />
          <Route path="/production/:id" element={<ProductionDetail />} />
          <Route path="/doctor-rewinder" element={<DoctorRewinder />} />
          <Route path="/doctor-rewinder/:id" element={<DoctorRewinderDetail />} />
          <Route path="/stock" element={<Stock />} />
          <Route path="/stock/lots" element={<Lots />} />
          <Route path="/stock/mouvements" element={<Mouvements />} />
          <Route path="/referentiel" element={<Referentiel />} />
          <Route path="/delegations" element={<Delegations />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  const { session, chargement } = useAuth();
  if (chargement) return <p className="vide" style={{ padding: 30 }}>Chargement…</p>;
  if (!session) return <Connexion />;
  if (session.utilisateur.doit_changer_mot_de_passe) return <ChangerMotDePasse />;
  if (session.double_facteur_a_configurer) return <ConfigurerDoubleFacteur />;
  return <Disposition />;
}
