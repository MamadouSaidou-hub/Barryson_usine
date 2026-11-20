import { useState, type FormEvent } from "react";
import { envoyer, lire, type S } from "../api";
import { DROITS_DELEGABLES, ROLES } from "../libelles";
import {
  Alerte,
  Badge,
  Bouton,
  Carte,
  Champ,
  Chargement,
  Choix,
  Page,
  Saisie,
  Tableau,
  Vide,
  date,
  messageErreur,
  useAnnuaire,
  useDonnees,
} from "../ui";

const dansJours = (n: number) => new Date(Date.now() + n * 86400000).toISOString().slice(0, 10);

export function Delegations() {
  const nom = useAnnuaire();
  const { donnees, erreur, chargement, recharger } = useDonnees(async () => {
    const [delegations, annuaire] = await Promise.all([
      lire<S["DelegationPublic"][]>("/api/delegations"),
      lire<S["EntreeAnnuaire"][]>("/api/annuaire"),
    ]);
    return { delegations, candidats: annuaire.filter((u) => u.actif && !["dg", "administrateur"].includes(u.role)) };
  });

  const [delegataire, setDelegataire] = useState("");
  const [droits, setDroits] = useState<string[]>(["achats.valider"]);
  const [jusquAu, setJusquAu] = useState(dansJours(14));
  const [motif, setMotif] = useState("");
  const [probleme, setProbleme] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  async function creer(e: FormEvent) {
    e.preventDefault();
    setEnvoi(true);
    setProbleme(null);
    try {
      await envoyer("/api/delegations", { delegataire_id: delegataire, permissions: droits, jusqu_au: jusquAu, motif });
      setDelegataire("");
      setMotif("");
      await recharger();
    } catch (err) {
      setProbleme(messageErreur(err));
    } finally {
      setEnvoi(false);
    }
  }

  async function revoquer(id: string) {
    setProbleme(null);
    try {
      await envoyer(`/api/delegations/${id}/revoquer`);
      await recharger();
    } catch (err) {
      setProbleme(messageErreur(err));
    }
  }

  const maintenant = Date.now();
  const etat = (d: S["DelegationPublic"]) =>
    d.revoquee_le ? { libelle: "Révoquée", ton: "neutre" as const } : new Date(d.date_fin).getTime() <= maintenant ? { libelle: "Expirée", ton: "neutre" as const } : { libelle: "En vigueur", ton: "ok" as const };

  return (
    <Page
      titre="Délégations"
      sousTitre="Vous pouvez confier certaines de vos validations à un collaborateur, pour une durée limitée. Vous restez responsable : chaque décision est tracée avec la mention de la délégation."
    >
      <Chargement erreur={erreur} chargement={chargement}>
        {donnees && (
          <div className="grille deux">
            <Carte titre="Désigner un délégataire">
              <form className="formulaire" onSubmit={creer}>
                <Champ etiquette="Délégataire">
                  <Choix value={delegataire} onChange={(e) => setDelegataire(e.target.value)}>
                    <option value="">— Choisir —</option>
                    {donnees.candidats.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.nom} — {ROLES[u.role]}
                      </option>
                    ))}
                  </Choix>
                </Champ>
                <fieldset style={{ border: "none", padding: 0, margin: 0 }}>
                  <legend className="champ-etiquette" style={{ marginBottom: 6 }}>
                    Validations confiées
                  </legend>
                  {Object.entries(DROITS_DELEGABLES).map(([cle, libelle]) => (
                    <label key={cle} className="case" style={{ marginBottom: 4 }}>
                      <input
                        type="checkbox"
                        checked={droits.includes(cle)}
                        onChange={(e) => setDroits(e.target.checked ? [...droits, cle] : droits.filter((d) => d !== cle))}
                      />
                      <span>{libelle}</span>
                    </label>
                  ))}
                </fieldset>
                <Champ etiquette="Jusqu'au (inclus)" aide="90 jours au plus. Vous pouvez révoquer à tout moment.">
                  <Saisie type="date" min={dansJours(1)} max={dansJours(90)} value={jusquAu} onChange={(e) => setJusquAu(e.target.value)} />
                </Champ>
                <Champ etiquette="Motif">
                  <Saisie value={motif} placeholder="ex. Absence en mission du 5 au 19 décembre" onChange={(e) => setMotif(e.target.value)} />
                </Champ>
                {probleme && <Alerte>{probleme}</Alerte>}
                <Bouton type="submit" chargement={envoi} disabled={!delegataire || droits.length === 0 || motif.trim().length < 5}>
                  Accorder la délégation
                </Bouton>
              </form>
            </Carte>

            <Carte titre="Délégations accordées">
              {donnees.delegations.length === 0 ? (
                <Vide>Aucune délégation pour le moment.</Vide>
              ) : (
                <Tableau colonnes={["Délégataire", "Droits", "Jusqu'au", "État", ""]}>
                  {donnees.delegations.map((d) => {
                    const e = etat(d);
                    return (
                      <tr key={d.id}>
                        <td>
                          <strong>{nom(d.delegataire_id)}</strong>
                          <div className="champ-aide">{d.motif}</div>
                        </td>
                        <td>{d.permissions.map((p) => DROITS_DELEGABLES[p] ?? p).join(", ")}</td>
                        <td>{date(d.date_fin)}</td>
                        <td>
                          <Badge ton={e.ton}>{e.libelle}</Badge>
                        </td>
                        <td>
                          {e.libelle === "En vigueur" && (
                            <Bouton variante="secondaire" onClick={() => revoquer(d.id)}>
                              Révoquer
                            </Bouton>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </Tableau>
              )}
            </Carte>
          </div>
        )}
      </Chargement>
    </Page>
  );
}
