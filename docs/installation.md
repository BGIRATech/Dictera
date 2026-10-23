# Dictera — installation, vérification, données

## Prérequis

- Windows 11 x64 et un GPU NVIDIA compatible CUDA 12 (testé : RTX 4070 Ti, pilote 617.42).
- Aucun toolkit CUDA ni cuDNN à installer : les DLL sont fournies avec Dictera.
- Aucune connexion réseau à l'usage. Le modèle Whisper est inclus dans le dossier packagé.

## Installer l'application packagée

1. Copier le dossier `dist\Dictera\` où l'on veut, par exemple `C:\Program Files\Dictera\` ou `%LOCALAPPDATA%\Programs\Dictera\`.
   - Il pèse environ 3,8 Go : 1,9 Go de DLL CUDA (cuBLAS et cuDNN) et 1,6 Go de modèle `large-v3-turbo`.
2. Lancer `Dictera.exe`.
   - Le Tableau de bord s'ouvre et l'icône apparaît dans la zone de notification.
   - Fermer la fenêtre la masque. Pour quitter, faire un clic droit sur l'icône puis **Quitter Dictera**.
   - Relancer `Dictera.exe` alors qu'il tourne déjà réaffiche simplement la fenêtre.
3. Facultatif : créer un raccourci dans `shell:startup` pour un lancement à l'ouverture de session.
4. Pour coller dans des fenêtres lancées en administrateur, lancer Dictera en administrateur.

## Vérifier une installation

```
Dictera.exe --self-test [phrase.wav]
```

L'autotest vérifie :
- la sonde GPU (CUDA, float16, cuBLAS, cuDNN) ;
- le modèle Whisper, chargé depuis le disque ;
- une vraie transcription, si un fichier WAV 16 kHz mono est fourni ;
- PortAudio et le micro ;
- SQLite ;
- l'interface Qt.

Le rapport est écrit dans `%LOCALAPPDATA%\Dictera\logs\self-test.txt`. Le code de retour vaut 0 si tout est OK. L'autotest ne touche ni au clavier, ni à l'historique, ni aux réglages.

## Données (toutes locales)

| Quoi | Où |
|---|---|
| Réglages | `%APPDATA%\Dictera\config.json` |
| Historique, dictionnaire, corrections | `%LOCALAPPDATA%\Dictera\dictera.db` (SQLite) |
| Journaux (jamais le texte dicté) | `%LOCALAPPDATA%\Dictera\logs\` |
| Modèles téléchargés (version développement) | `%LOCALAPPDATA%\Dictera\models\` |

- L'audio n'est jamais écrit sur le disque.
- « Tout effacer », dans l'Historique, supprime réellement les textes du fichier.

**Désinstaller** : quitter Dictera, supprimer le dossier de l'application, puis, pour effacer aussi les données, `%APPDATA%\Dictera` et `%LOCALAPPDATA%\Dictera`.

## Développement

```
cd D:\Dictera
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python scripts\fetch_models.py            # une fois : seule étape réseau
.venv\Scripts\python -m dictera                         # lancer
.venv\Scripts\python -m dictera --self-test             # autotest
```

**Construire l'exécutable** : `pip install pyinstaller`, puis `.venv\Scripts\python packaging\build.py`.
- Option `--no-model` pour ne pas inclure le modèle, `--model large-v3` pour choisir le modèle de précision maximale.
- Résultat : `dist\Dictera\Dictera.exe`.
- Le build est en un seul dossier (onedir) : un fichier unique (onefile) décompresserait environ 1,9 Go de DLL à chaque lancement.

## Tests

| Script | Couvre |
|---|---|
| `scripts\test_phase1.py [--key F24]` | touche push-to-talk et capture micro |
| `scripts\test_phase2.py` | sonde GPU, transcription, latence |
| `scripts\test_phase3.py [--audio] [--keys shift+insert]` | reformulation, collage dans la fenêtre capturée, restauration du presse-papiers |
| `scripts\test_phase4.py` | historique, statistiques, dictionnaire (base temporaire) |
| `scripts\test_phase5.py` | les 4 pages de l'interface (base et config temporaires) |
| `scripts\test_e2e.py` | bout en bout dans la vraie application : touche, moteur GPU, collage, historique, interface |

- Les tests n'utilisent jamais les données réelles.
- Si une instance de Dictera tourne déjà, utiliser `--key F24` pour la Phase 1. Le test de bout en bout utilise F24 d'office.
