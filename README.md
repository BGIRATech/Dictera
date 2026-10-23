# Dictera

**Dictée vocale 100 % locale pour Windows 11.** Maintenez une touche, parlez, relâchez : le texte, mis au propre, est collé dans l'application où vous étiez.

> Ta voix ne quitte jamais ce PC.

- La transcription tourne sur votre GPU (faster-whisper, modèle `large-v3-turbo`).
- La reformulation est faite par des règles, ou par un LLM local (LM Studio ou Ollama).
- L'historique est enregistré dans un fichier SQLite local.
- Aucun compte, aucune télémétrie, aucune clé d'API. Le réseau ne sert qu'une fois, au téléchargement du modèle Whisper.

## Fonctionnalités

- **Push-to-talk global**, via un hook clavier bas niveau.
  - La touche est configurable : Ctrl droit par défaut, ou F13 à F24 pour une touche de souris programmée.
  - Les frappes synthétisées par un logiciel de périphérique sont acceptées.
  - Un appui de moins de 200 ms est ignoré.
  - Une autre touche pressée pendant le maintien annule la dictée : c'était un raccourci.
- **Collage dans la bonne fenêtre**, celle qui était active à l'appui, même si le focus a changé entre-temps.
  - Le presse-papiers est sauvegardé, puis restauré après le collage, dans tous ses formats.
  - Le texte dicté est exclu de l'historique Win+V et du presse-papiers cloud.
- **Mise au propre**, au choix :
  - **Règles** :
    - retrait des « euh » ;
    - ponctuation et majuscules ;
    - symboles dictés : « arobase », « point », « tiret », « slash »… ;
    - adresses mail et URL reconstruites, par exemple `sophie@gmail.com`.
  - **LLM local** via un serveur compatible OpenAI (LM Studio) ou Ollama :
    - en cas d'échec, repli silencieux sur les règles : serveur injoignable ou trop lent (délai réglable, 3 s par défaut) ;
    - un garde-fou écarte les sorties qui « répondent » à la dictée au lieu de la nettoyer.
- **Dictionnaire personnel** :
  - « Mes mots à moi » sert d'amorce à Whisper ;
  - les corrections automatiques transforment ce qui est entendu en ce qui doit s'écrire, par exemple « ski » → « skill ».
- **Interface sombre en 4 pages** :
  - **Tableau de bord** : mots du jour, vitesse, temps gagné, histogramme sur 14 jours, applis où vous dictez ;
  - **Historique** : recherche et filtres, effacement réel du texte dans le fichier ;
  - **Dictionnaire** ;
  - **Réglages** : modèle, langue, micro, touche, LLM avec sa liste de modèles chargée dynamiquement.

## Prérequis

- Windows 11 x64.
- Un GPU NVIDIA compatible CUDA 12. Les DLL cuBLAS et cuDNN viennent des paquets pip : aucun toolkit CUDA à installer.
- Python 3.11 ou plus récent.
- Facultatif : [LM Studio](https://lmstudio.ai/), avec son serveur local activé, pour la reformulation par LLM.

## Installation (depuis les sources)

```powershell
git clone https://github.com/BGIRATech/Dictera.git
cd Dictera
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python scripts\fetch_models.py      # télécharge large-v3-turbo (≈1,6 Go), une seule fois
.venv\Scripts\python -m dictera                   # lancer
```

- Au lancement, le Tableau de bord s'ouvre et l'icône apparaît dans la zone de notification.
- Fermer la fenêtre la masque. Pour quitter, faire un clic droit sur l'icône puis **Quitter Dictera**.
- Vérifier une installation : `.venv\Scripts\python -m dictera --self-test`.

## Construire l'exécutable

```powershell
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python packaging\build.py           # options : --no-model, --model large-v3
```

- Résultat : `dist\Dictera\Dictera.exe`, un dossier d'environ 3,8 Go, modèle Whisper inclus.
- Le format est un dossier plutôt qu'un fichier unique : un fichier unique décompresserait environ 1,9 Go de DLL CUDA à chaque lancement.

## Réglages

Tout se règle depuis la page **Réglages**. Ils sont enregistrés dans `%APPDATA%\Dictera\config.json`. Le fichier [`config.example.json`](config.example.json) donne toutes les clés et leurs valeurs par défaut.

| Clé | Rôle |
|---|---|
| `hotkey` | touche à maintenir (`RCTRL`, `F13`…`F24`, …) |
| `whisper_model` | `large-v3-turbo` (rapide) ou `large-v3` (précision maximale) |
| `reformulation` | `auto` (LLM si disponible, sinon règles), `rules` ou `off` |
| `llm_url` | URL du serveur LLM : locale uniquement, une URL distante est refusée |
| `llm_model` | identifiant du modèle dans LM Studio, par exemple `mistralai/mistral-nemo-instruct-2407` |
| `llm_timeout_s`, `llm_temperature` | délai au-delà duquel les règles prennent le relais, et température |
| `paste_delay_ms`, `restore_delay_ms` | délais du collage et de la restauration du presse-papiers |

## Données et vie privée

| Quoi | Où |
|---|---|
| Réglages | `%APPDATA%\Dictera\config.json` |
| Historique et dictionnaire | `%LOCALAPPDATA%\Dictera\dictera.db` |
| Journaux | `%LOCALAPPDATA%\Dictera\logs\` |

- **L'audio** est traité en mémoire et n'est jamais écrit sur le disque.
- **Les journaux** ne contiennent jamais le texte dicté.
- **Le titre de la fenêtre active** sert seulement à coller au bon endroit et à reconnaître quelques sites connus dans le navigateur. Il n'est jamais enregistré.
- **Le LLM** n'est contacté que sur la machine locale (`localhost` ou `127.0.0.1`).
- **« Tout effacer »** supprime réellement les textes du fichier (`secure_delete`, puis `VACUUM`).

## Tests

Les scripts de `scripts\` utilisent des bases et des réglages temporaires, jamais les vôtres.

| Script | Couvre |
|---|---|
| `test_phase1.py` | touche push-to-talk et capture micro |
| `test_phase2.py` | sonde GPU, transcription, latence |
| `test_phase3.py` | reformulation, collage dans la fenêtre capturée, restauration du presse-papiers |
| `test_phase4.py` | historique, statistiques, dictionnaire |
| `test_phase5.py` | les 4 pages de l'interface |
| `test_symbols.py` | symboles dictés et adresses |
| `test_llm.py` | reformulation par LLM local, repli sur les règles, bloc `<think>` |
| `test_e2e.py` | bout en bout dans la vraie application, avec une voix de synthèse |

## Structure

```
dictera/            application (hook, audio, transcription, reformulation, insertion, stockage)
dictera/ui/         interface Qt (PySide6) : thème, composants, 4 pages
packaging/          build PyInstaller (spec, lanceur, script de build)
scripts/            téléchargement du modèle et tests
docs/               spécification produit, installation
```

## Limites connues

- **Adresses dictées** : Whisper normalise parfois une adresse dictée et peut en perdre une partie (« arobase », voire le domaine). Le LLM rattrape souvent l'adresse, mais relisez les adresses importantes.
- **Fenêtres administrateur** : coller dans une fenêtre lancée en administrateur exige de lancer Dictera en administrateur. Sinon, le texte reste dans le presse-papiers.
- **Langue** : la mise au propre (règles et consigne du LLM) est prévue pour le français.

## Licence

[MIT](LICENSE).

Les modèles et bibliothèques utilisés gardent leur propre licence :
- les modèles Whisper sont publiés par OpenAI sous licence MIT ;
- PySide6 est sous LGPL ;
- les DLL NVIDIA CUDA sont soumises à la licence NVIDIA. Elles sont incluses dans l'exécutable construit, pas dans ce dépôt.
