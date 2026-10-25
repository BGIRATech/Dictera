# Dictera — spécification produit (v1 · Windows 11 · 100 % local)

## 0. Moteur (local, sur le GPU)

- Transcription : faster-whisper (CTranslate2) sur CUDA, RTX 4070 Ti, en float16.
  Modèle par défaut large-v3-turbo (multilingue, rapide) ; option « précision
  maximale » : large-v3. Modèle configurable dans les Réglages.
- Reformulation FR (retrait des « euh », ponctuation, casse) : LLM local via Ollama
  (Llama 3.1 8B) OU règles simples — réglable, désactivable.
- Stockage : SQLite local. Aucune connexion réseau pour la dictée. Aucune clé tierce.
- Principe affiché partout : « Ta voix ne quitte jamais ce PC. »

## 1. Fonctionnement

- Appli native Windows vivant dans la zone de notification (system tray).
- Je maintiens Ctrl droit (configurable), je parle, je relâche.
- Ma voix est transcrite en local, reformulée proprement en français (sans « euh »,
  avec ponctuation), puis le texte est collé automatiquement dans l'appli active.
- Le presse-papiers est restauré à son contenu d'origine après le collage.

## 2. Identité visuelle

Interface sombre, ultra-moderne, minimaliste et élégante — logiciel de productivité
premium pour Windows 11. Sobre, précis, raffiné ; hiérarchie nette, espace maîtrisé.

- Palette : fond #111416 ; surfaces secondaires #191E21 ; séparateurs #2A3235 ;
  texte principal #F1F4F4 ; texte secondaire #929DA1 ; accent turquoise #6DA3AE.
- Cartes/panneaux : surfaces plates ou subtilement contrastées, contours fins, ombres
  presque imperceptibles, angles légèrement arrondis (rayon modéré, cohérent).
  Aucun arrondi excessif, aucune bulle.
- Typographie : sans-serif moderne très lisible ; hiérarchie claire titres / chiffres
  clés / libellés / secondaire. Précision avant décoration.
- Icônes : fines, en contour, cohérentes, discrètes.
- Mise en page : grille rigoureuse, alignements impeccables, marges généreuses,
  espaces réguliers ; tableaux/graphiques/listes compacts.
- Interactions : animations courtes et fluides, survols subtils, états actifs nets.
- Données : turquoise réservé aux données importantes / éléments interactifs ;
  nuances sobres pour le reste.
- Effets : profondeur par contrastes de surface et lignes fines. Pas de dégradé
  criard, néon, transparence décorative ni glassmorphism envahissant.
- Cohérence du langage visuel sur les 4 pages.
- Règle : chaque élément a une fonction claire ; lignes fines > gros blocs ;
  contrastes subtils > couleurs criardes ; qualité des espacements > décor.

## 3. Menu de gauche

- En haut : logo Dictera = onde sonore blanche dans un carré turquoise arrondi.
- Dessous : Tableau de bord, Historique, Dictionnaire, Réglages.

## 4. Page Tableau de bord

- Bandeau d'accueil turquoise en dégradé : « Salut <prénom> », rappel de la touche,
  petite onde sonore à droite.
- Quatre cartes de chiffres clés (icône dans un rond turquoise clair) :
  - Mots dictés aujourd'hui + écart en % vs hier.
  - Total des mots + nombre de dictées en dessous.
  - Vitesse moyenne en mots/minute.
  - Temps gagné (h/min) vs ma vitesse au clavier.
- Histogramme des mots dictés par jour sur 14 jours (barres turquoise, valeur au
  survol) + série de jours d'affilée avec une petite flamme.
- Graphique « Où je dicte » : top 5 des applis, barres horizontales, % de mots.
- Mes 5 dernières dictées : heure, nom de l'appli en pastille turquoise, nombre de
  mots, texte sur deux lignes, bouton copier.

## 5. Page Historique

- Barre de recherche + filtres : aujourd'hui, 7 jours, tout, et par appli.
- Dictées regroupées par jour : Aujourd'hui, Hier, puis la date.
- Par dictée : heure, pastille d'appli, nombre de mots, vitesse, texte final,
  transcription brute dépliable, bouton copier, bouton supprimer.
- En haut à droite : « Tout effacer » avec confirmation.

## 6. Page Dictionnaire

- Carte en tête : nombre de mots du dictionnaire + nombre de corrections cette semaine.
- « Mes mots à moi » : liste éditable (noms, marques, jargon). Injectés en local comme
  hotwords/amorce du modèle Whisper à chaque dictée (jamais envoyés sur un réseau).
- « Corrections automatiques » : tableau deux colonnes « ce qui est entendu » →
  « ce qui doit s'écrire » (ex. « ski » → « skill »), appliquées en post-traitement
  local, bouton d'ajout.

## 7. Page Réglages

- Moteur & vie privée : badges Transcription = Local (large-v3-turbo ou large-v3,
  CUDA) ; Reformulation
  = Local (Llama 3.1 8B) ou Désactivée ; Historique = Local (SQLite). Phrase :
  « Ta voix ne quitte jamais ce PC. » Choix du modèle Whisper et du périphérique.
- Autorisations : état du micro, bouton « Ouvrir les réglages de confidentialité
  Windows (Microphone) ». Note : coller dans une fenêtre lancée en administrateur
  exige de lancer Dictera en administrateur.
- Dictée : la touche (défaut Ctrl droit), la langue (fr), sons de début/fin,
  restaurer ou non le presse-papiers, montrer ou non la dictée dans Wisp (activé par
  défaut ; sans effet si Wisp n'est pas lancé).
- Mise au propre : interrupteur de reformulation + modèle utilisé.
- Stats : ma vitesse au clavier (mots/min) pour le calcul du temps gagné.

## 8. Données & vie privée

- 100 % local : audio traité en mémoire, jamais stocké ni transmis.
- L'historique (texte brut + reformulé + appli + heure + mots + wpm) est en SQLite
  local, effaçable depuis l'Historique.
- La fenêtre active est lue uniquement pour coller et étiqueter l'historique ; jamais
  envoyée. Aucune télémétrie, aucune clé.
- Wisp (compagnon de bureau, optionnel) ne reçoit que l'état de la dictée, par un canal
  nommé local réservé au compte Windows : écoute et niveau du micro, transcription,
  nombre de mots collés, erreur. Ni le texte dicté, ni le nom de l'appli cible.

## 9. Règles & valeurs par défaut

- Dictionnaire pré-rempli : Claude Code, skill, prompt, to-do.
- Au lancement, ouvrir directement le Tableau de bord.
- config.json (%APPDATA%\Dictera) : min_hold_ms, défaut 200 — un maintien de la touche
  plus court est considéré comme accidentel et ignoré (aucune transcription).

## 10. Stack

- Python 3.11+ ; faster-whisper (CUDA) ; Ollama (optionnel) ; pywin32/ctypes pour
  Win32 (hook clavier bas niveau, SendInput, presse-papiers, fenêtre active) ;
  UI sombre (à arrêter en Phase UI) ; SQLite ; packaging PyInstaller x64.
