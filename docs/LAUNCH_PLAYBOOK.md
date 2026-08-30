# Launch Playbook : lancement du repo (juillet 2026)

Interne au repo (pas listé dans le README). Séquencement optimisé : d'abord la preuve sociale technique, ensuite les listes, ensuite les canaux grand public.

## J0 : Publication

1. **Repo public** `grafana-llmops-forge`, description : *« Point it at any Grafana → full AI/LLM observability: FinOps by sovereignty, agents, EU AI Act, generated, deployed, vision-verified. Zero-dependency Agent Skill + CLI. »*
2. **Topics** (l'algorithme de découverte GitHub) : `llmops` `llm-observability` `ai-observability` `grafana` `grafana-dashboards` `prometheus` `opentelemetry` `finops` `eu-ai-act` `ai-governance` `vllm` `litellm` `claude-skills` `agent-skills` `claude-code` `sre`
3. **Social preview** : uploader `docs/assets/social-preview.png` (Settings → General → Social preview) ; c'est l'image des partages X/LinkedIn/Slack.
4. **Release v1.1.0** avec le `.skill` en asset (les catalogues type Chat2AnyLLM indexent les SKILL.md automatiquement une fois le repo référencé).
5. Activer Discussions ; épingler une discussion « Show us your forge output (redacted) » ; les captures partagées servent de preuve sociale.
6. Vérifier que le badge CI passe au vert (le workflow tourne offline, aucune raison d'échouer).

## Ordre corrigé par l'expérience : traction D'ABORD, listes ensuite

La première campagne de soumissions a été instructive. `BehiSecc` a fermé la PR
avec un motif explicite : *« the AI skill currently has fewer than 60 stars, and
we're only accepting skills above that threshold »*. Plusieurs listes de skills
filtrent sur les étoiles : **elles récompensent la traction, elles ne la créent
pas**. Soumettre trop tôt brûle une cartouche : une fois la PR fermée, resoumettre
agace le mainteneur.

Séquence corrigée :
1. Show HN, puis Reddit à 24-48 h d'intervalle → premières centaines d'étoiles
2. Grafana Community Dashboards (publier le JSON portable via `--export-portable`)
3. **Ensuite** les listes de skills, une fois passé le seuil de 60-100 étoiles
4. Marketplace Anthropic en dernier

État de la première vague : `adriannovegil/awesome-observability` **mergée** ;
`ComposioHQ`, `travisvn` et `obviousworks` ouvertes ; `tensorchord` et `BehiSecc`
fermées : la seconde sur le seuil d'étoiles, la première avec des contrôles CI en
échec à vérifier avant resoumission.

## Les listes GitHub (PR ciblées), après la traction

Règle d'or : **une PR = une ligne au format exact de la liste**, description ≤ 1 phrase, pas d'auto-promo dans le texte de PR. Ordre de priorité :

| Liste | Section cible | Ligne à proposer (adapter au format local) |
|---|---|---|
| `tensorchord/Awesome-LLMOps` (~5k★, LA référence) | Observability | `grafana-llmops-forge: Turn any Grafana into an AI observability suite: auto-discovery, 6 generated dashboards (FinOps by sovereignty, agents, EU AI Act), vision-verified rendering. Zero deps.` |
| `hesreallyhim/awesome-claude-code` (~28k★) | Skills / Plugins | `grafana-llmops-forge: Skill that audits a Grafana instance, forges & deploys LLM observability dashboards (FinOps, agents, EU AI Act), then verifies rendering by vision.` |
| `ComposioHQ/awesome-claude-skills` | DevOps/Infra | idem ci-dessus |
| `travisvn/awesome-claude-skills` | Infrastructure | idem |
| `BehiSecc/awesome-claude-skills` | Ops/Monitoring | idem |
| `obviousworks/Claude-AI-skills-collection-2026` | (process: PR ou issue avec repo link) | insister zéro-dépendance ; leur README met en avant l'audit sécurité Snyk, notre stdlib-only est l'argument |
| `adriannovegil/awesome-observability` (actif 05/2026) | LLM/AI section | version « observability » de la ligne |
| `awesomelistsio/awesome-llmops` | Monitoring & Observability | idem |
| `ashishpatel26/awesome-open-source-llmops` | Observability | idem |
| `anthropics/skills` marketplace | soumission officielle | viser après ~200★ (précédent : Superpowers accepté) |

Bonus FR : `french-tech` awesome lists éventuelles + Grafana Community Dashboards (publier le JSON du FinOps sur grafana.com/dashboards avec lien repo ; canal de découverte des admins Grafana).

## J3-J7 : Canaux (dans cet ordre)

1. **Show HN** (mardi ou mercredi, 15h-17h CET = matin US), titre sobre et factuel :
   *« Show HN: Point it at any Grafana, get LLM FinOps + EU AI Act dashboards, vision-verified »*
   Premier commentaire (le vrai pitch) : le bug gpt-5.4-mini ×5,5 trouvé par l'audit, le choix stdlib-only post-ToxicSkills, la boucle vision. HN adore les post-mortems de ses propres bugs.
2. **r/grafana** (angle : « I built a generator that only creates panels your metrics can actually answer ») + **r/sre** + **r/LocalLLaMA** (angle vLLM/KV-cache/GPU + benchmark coût API vs self-hosted) + **r/devops**. Un post par sub, adapté, à 24h d'intervalle.
3. **Grafana Community Forum** (community.grafana.com, catégorie Dashboards) ; les mainteneurs Grafana repèrent et relaient parfois.
4. **LinkedIn FR**, angle AI Act : *« Le 2 août 2026, les sanctions de l'AI Act s'activent. Voici le dashboard Grafana que votre auditeur voudra voir, généré en 3 commandes. »* + captures FR.
5. **X/Twitter** : thread 6 tweets = 6 dashboards, 1 visuel chacun, finir sur la boucle vision (le GIF/screenshot du verdict ✅⚠❌).
6. **Newsletter pitchs** : TLDR DevOps, Last Week in AWS (angle FinOps), MLOps Community Slack (#llmops).

## Amplificateurs

- **GIF terminal** (asciinema → gif) des 3 commandes + sortie discover : à ajouter en haut du README dès que possible ; c'est ce qui fait le plus cliquer sur un repo outil.
- Badge « works with Agent Skills standard » → issue sur agentskills.io pour figurer dans leur showcase.
- Chaque étoile-jalon (100/500/1k) = un post « what changed » avec les contributions registre (preuve de communauté vivante).
- Répondre à TOUTES les issues < 24h les 3 premières semaines : la vélocité de réponse est un signal de ranking implicite des listes awesome.

## Ce qu'on ne fait pas

Pas de stars achetées/échangées (les mainteneurs de listes vérifient les graphes d'étoiles), pas de repost multi-subs le même jour, pas de « please star ». Le repo se vend par la démo.
