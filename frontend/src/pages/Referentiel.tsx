import { useState, type FormEvent } from "react";
import { envoyer, lire, type S } from "../api";
import { useAuth } from "../auth";
import { NIVEAUX } from "../libelles";
import { Alerte, Badge, Bouton, Carte, Champ, Chargement, Choix, Page, Saisie, Tableau, Vide, messageErreur, nombre, useDonnees } from "../ui";

function FormulaireArticle({ onFermer, onCree }: { onFermer: () => void; onCree: () => void }) {
  const [code, setCode] = useState("");
  const [nom, setNom] = useState("");
  const [niveau, setNiveau] = useState("semi_fini");
  const [unite, setUnite] = useState("piece");
  const [seuil, setSeuil] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  async function soumettre(e: FormEvent) {
    e.preventDefault();
    setEnvoi(true);
    setErreur(null);
    try {
      await envoyer("/api/articles", {
        code,
        nom,
        niveau_stock: niveau,
        unite_gestion: unite,
        seuil_min: seuil ? seuil.replace(",", ".") : null,
      });
      onCree();
    } catch (err) {
      setErreur(messageErreur(err));
      setEnvoi(false);
    }
  }

  return (
    <div className="voile" role="dialog" aria-modal="true">
      <form className="modale" onSubmit={soumettre}>
        <h2>Nouvel article</h2>
        <div className="rangee">
          <Champ etiquette="Code" aide="Lettres, chiffres, tirets. Ne change jamais.">
            <Saisie value={code} onChange={(e) => setCode(e.target.value)} />
          </Champ>
          <Champ etiquette="Unité de gestion">
            <Choix value={unite} onChange={(e) => setUnite(e.target.value)}>
              {["piece", "rouleau", "carton", "kg", "m", "panier"].map((u) => (
                <option key={u}>{u}</option>
              ))}
            </Choix>
          </Champ>
        </div>
        <Champ etiquette="Nom">
          <Saisie value={nom} onChange={(e) => setNom(e.target.value)} />
        </Champ>
        <div className="rangee">
          <Champ etiquette="Niveau de stock" aide="Définitif : un article reste toujours au même niveau.">
            <Choix value={niveau} onChange={(e) => setNiveau(e.target.value)}>
              <option value="semi_fini">{NIVEAUX.semi_fini}</option>
              <option value="produit_fini">{NIVEAUX.produit_fini}</option>
            </Choix>
          </Champ>
          <Champ etiquette="Seuil minimum (alerte)">
            <Saisie inputMode="decimal" value={seuil} onChange={(e) => setSeuil(e.target.value)} />
          </Champ>
        </div>
        {erreur && <Alerte>{erreur}</Alerte>}
        <div className="actions droite">
          <Bouton type="button" variante="secondaire" onClick={onFermer}>
            Annuler
          </Bouton>
          <Bouton type="submit" chargement={envoi} disabled={code.length < 2 || nom.length < 2}>
            Créer
          </Bouton>
        </div>
      </form>
    </div>
  );
}

function FormulaireFournisseur({ onFermer, onCree }: { onFermer: () => void; onCree: () => void }) {
  const [champs, setChamps] = useState({ code: "", nom: "", pays: "", telephone: "", email: "", conditions_paiement: "", delai: "" });
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);
  const maj = (cle: keyof typeof champs, valeur: string) => setChamps({ ...champs, [cle]: valeur });

  async function soumettre(e: FormEvent) {
    e.preventDefault();
    setEnvoi(true);
    setErreur(null);
    try {
      await envoyer("/api/fournisseurs", {
        code: champs.code,
        nom: champs.nom,
        pays: champs.pays || null,
        telephone: champs.telephone || null,
        email: champs.email || null,
        conditions_paiement: champs.conditions_paiement || null,
        delai_livraison_jours: champs.delai ? Number(champs.delai) : null,
      });
      onCree();
    } catch (err) {
      setErreur(messageErreur(err));
      setEnvoi(false);
    }
  }

  return (
    <div className="voile" role="dialog" aria-modal="true">
      <form className="modale" onSubmit={soumettre}>
        <h2>Nouveau fournisseur</h2>
        <div className="rangee">
          <Champ etiquette="Code">
            <Saisie value={champs.code} onChange={(e) => maj("code", e.target.value)} />
          </Champ>
          <Champ etiquette="Pays">
            <Saisie value={champs.pays} onChange={(e) => maj("pays", e.target.value)} />
          </Champ>
        </div>
        <Champ etiquette="Nom">
          <Saisie value={champs.nom} onChange={(e) => maj("nom", e.target.value)} />
        </Champ>
        <div className="rangee">
          <Champ etiquette="Téléphone">
            <Saisie value={champs.telephone} onChange={(e) => maj("telephone", e.target.value)} />
          </Champ>
          <Champ etiquette="E-mail">
            <Saisie type="email" value={champs.email} onChange={(e) => maj("email", e.target.value)} />
          </Champ>
        </div>
        <div className="rangee">
          <Champ etiquette="Conditions de paiement">
            <Saisie value={champs.conditions_paiement} onChange={(e) => maj("conditions_paiement", e.target.value)} />
          </Champ>
          <Champ etiquette="Délai de livraison (jours)">
            <Saisie inputMode="numeric" value={champs.delai} onChange={(e) => maj("delai", e.target.value.replace(/\D/g, ""))} />
          </Champ>
        </div>
        {erreur && <Alerte>{erreur}</Alerte>}
        <div className="actions droite">
          <Bouton type="button" variante="secondaire" onClick={onFermer}>
            Annuler
          </Bouton>
          <Bouton type="submit" chargement={envoi} disabled={champs.code.length < 2 || champs.nom.length < 2}>
            Créer
          </Bouton>
        </div>
      </form>
    </div>
  );
}

export function Referentiel() {
  const { peut } = useAuth();
  const [modale, setModale] = useState<"article" | "fournisseur" | null>(null);
  const voitArticles = peut("referentiels.consulter");
  const voitFournisseurs = peut("achats.consulter");
  const { donnees, erreur, chargement, recharger } = useDonnees(async () => {
    const [articles, fournisseurs] = await Promise.all([
      voitArticles ? lire<S["ArticlePublic"][]>("/api/articles") : [],
      voitFournisseurs ? lire<S["FournisseurPublic"][]>("/api/fournisseurs") : [],
    ]);
    return { articles, fournisseurs };
  });

  return (
    <Page titre="Articles et fournisseurs" sousTitre="Les fiches de base utilisées partout : achats, stock, production.">
      <Chargement erreur={erreur} chargement={chargement}>
        {donnees && (
          <div className="grille deux">
            {voitArticles && (
              <Carte titre="Articles" droite={peut("referentiels.saisir") && <Bouton variante="secondaire" onClick={() => setModale("article")}>+ Article</Bouton>}>
                {donnees.articles.length === 0 ? (
                  <Vide>Aucun article.</Vide>
                ) : (
                  <Tableau colonnes={["Code", "Nom", "Niveau", { texte: "Seuil min.", droite: true }]}>
                    {donnees.articles.map((a) => (
                      <tr key={a.id}>
                        <td className="mono">{a.code}</td>
                        <td>
                          {a.nom} {!a.actif && <Badge ton="neutre">Désactivé</Badge>}
                        </td>
                        <td>{NIVEAUX[a.niveau_stock]}</td>
                        <td className="droite">{a.seuil_min === null ? "—" : `${nombre(a.seuil_min)} ${a.unite_gestion}`}</td>
                      </tr>
                    ))}
                  </Tableau>
                )}
              </Carte>
            )}
            {voitFournisseurs && (
              <Carte titre="Fournisseurs" droite={peut("achats.saisir") && <Bouton variante="secondaire" onClick={() => setModale("fournisseur")}>+ Fournisseur</Bouton>}>
                {donnees.fournisseurs.length === 0 ? (
                  <Vide>Aucun fournisseur.</Vide>
                ) : (
                  <Tableau colonnes={["Nom", "Pays", { texte: "Délai", droite: true }]}>
                    {donnees.fournisseurs.map((f) => (
                      <tr key={f.id}>
                        <td>
                          <strong>{f.nom}</strong>
                          <div className="champ-aide">{f.code}</div>
                        </td>
                        <td>{f.pays ?? "—"}</td>
                        <td className="droite">{f.delai_livraison_jours === null ? "—" : `${f.delai_livraison_jours} j`}</td>
                      </tr>
                    ))}
                  </Tableau>
                )}
              </Carte>
            )}
          </div>
        )}
      </Chargement>
      {modale === "article" && <FormulaireArticle onFermer={() => setModale(null)} onCree={() => { setModale(null); recharger(); }} />}
      {modale === "fournisseur" && <FormulaireFournisseur onFermer={() => setModale(null)} onCree={() => { setModale(null); recharger(); }} />}
    </Page>
  );
}
