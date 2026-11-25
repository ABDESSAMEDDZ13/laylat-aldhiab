# ليلة الذئاب — V0.1

Jeu web multijoueur, interface arabe RTL conçue pour les téléphones. Serveur Python/aiohttp, WebSocket, audio Web Audio (PCM 16 kHz). Aucun compte LiveKit ni clé API nécessaire pour ce prototype.

## Démarrage local

Python 3.11+ :

```sh
python -m venv .venv
# macOS/Linux : source .venv/bin/activate
# Windows : .venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

Ouvrir `http://localhost:8080` sur la machine. Pour simuler plusieurs joueurs, ouvrir des fenêtres indépendantes (sessions distinctes). Pour jouer sur plusieurs téléphones, publier le serveur derrière **HTTPS/WSS** avec prise en charge des WebSockets ; HTTP sur une IP LAN ne donne généralement pas accès au microphone. Le serveur doit rester actif (pas un hébergement statique). Dockerfile fourni : `docker build -t laylat-aldhiab .` puis `docker run --rm -p 8080:8080 laylat-aldhiab`.

## Déploiement

Créer un service web Python ou Docker sur un hébergeur prenant en charge les connexions WebSocket longues et HTTPS, importer ce dossier (par exemple depuis un dépôt Git), utiliser `pip install -r requirements.txt` puis `python server.py`, et conserver une seule instance pour ce MVP. Le port est lu dans `PORT`. Ne pas exposer le service sans TLS. Partager l'URL HTTPS ; chaque joueur active le son une fois et autorise le micro. Utiliser des écouteurs, conserver l'onglet au premier plan. Le serveur ne stocke pas les trames audio sur disque ; il les relaie aux destinataires autorisés. Ce n'est pas un chiffrement de bout en bout : TLS protège le transport, le serveur relaie le son.

## Règles

- Nombre de loups au choix de l'hôte : 1 (tue et réduit au silence, adapté à 5 joueurs), 2 (répartition initiale) ou 3 (à partir de 7 joueurs). Le mode à un loup conserve le médecin, le sorcier et les autres règles.
- Salle d'attente : conversation vocale entre les joueurs de la même salle après activation du son et autorisation du microphone. Chaque joueur peut couper/rétablir son micro sans couper l'écoute. Au démarrage, les règles de parole et les canaux privés de la partie prennent automatiquement le relais.
- Minimum 5 joueurs ; 2 loups spéciaux, médecin, sorcier, SV. Option troisième loup à partir de 7 joueurs. Limite technique provisoire de 30 joueurs, nombre de nuits illimité.
- Début directement la nuit : loups, sorcier, médecin. Les loups se reconnaissent et discutent dans un canal privé contrôlé côté serveur. Le noir tue, le silencieux fait taire, le survivant spécial récupère les deux pouvoirs si nécessaire, puis le loup normal si les deux spéciaux meurent. Les loups ne peuvent pas s'entretuer, mais peuvent se faire taire entre eux. La même cible ne peut pas être réduite au silence deux nuits de suite.
- Sorcier : une vie, une mort, utilisables ensemble ; la victime des loups est visible uniquement tant que la potion de vie est disponible. Le médecin peut protéger contre les deux types de mise à mort ; protection illimitée, sauf lui-même deux nuits consécutives. Aucune protection contre le silence.
- Jour : rotation du premier joueur chaque jour, micro individuel (30 à 120 s), bouton terminer. Un joueur silencieux ne parle pas pendant le tour ordinaire, mais vote, conserve ses pouvoirs et peut parler en débat.
- Vote public séquentiel et définitif avec 60 secondes par joueur par défaut. À expiration, le tour passe sans enregistrer de voix ; vote sur soi autorisé. Tous les ex æquo débattent (1–3 min chacun), puis ne votent pas au deuxième tour. Deuxième égalité : personne ne meurt, nouvelle nuit. Rôle révélé à l'élimination, aucun dernier mot. Les loups gagnent à la parité ou au-delà ; le village gagne lorsque tous les loups sont éliminés.
- Déconnexion d'un vivant : pause automatique ; l'hôte attend le retour ou exclut le joueur. L'hôte participe normalement sans accès privilégié aux rôles.

## Choix provisoires (non confirmés)

- Nom de travail : ليلة الذئاب. Pas de narrateur vocal ni nouveaux rôles dans cette version.
- Durées par défaut : 60 s parole, 120 s débat, 120 s loups, 30 s sorcier, 30 s médecin ; les trois délais de nuit sont configurables. À expiration sans action, le pouvoir non utilisé est ignoré ; pas de cible automatique. Le loup peut renoncer au silence. Les joueurs ne peuvent pas se tuer eux-mêmes avec une potion ni se faire taire eux-mêmes. Les phases de nuit se terminent dès validation des actions nécessaires ; les rôles morts ou sans pouvoir sont sautés.
- En cas de déconnexion de l'hôte, la responsabilité est transférée à un joueur vivant connecté. Pas de persistance des parties après redémarrage, pas de comptes, pas de limitation anti-abus complète, ni audit de sécurité de production. L'audio est en PCM sans codec adaptatif ; la bande passante et la latence doivent être mesurées sur téléphones réels avant usage régulier, ou migrer vers un SFU WebRTC (ex. LiveKit).
- Pas de PWA installable dans cette première version. Les navigateurs peuvent couper le micro en arrière-plan. Le serveur contrôle qui reçoit le son, mais un joueur pourrait toujours communiquer en dehors du jeu.

## Tests

```sh
python -m unittest -v test_game
```

7 tests réussis dans l'environnement de création : règles, héritage des pouvoirs, secrets, potions, médecin, silence, égalité et revote, déconnexion/victoire, isolation de trames audio sur de vraies connexions WebSocket de test. Les fichiers JS passent `node --check`. Le test navigateur n'a pas pu être réalisé : l'environnement bloque l'accès local via Chromium. Le micro réel, Safari/iOS, Android, les performances, le déploiement public et la sécurité de production restent à valider.
