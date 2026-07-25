import sys
import os

# 🎯 INJECTION DU DOSSIER PARENT (Racine du projet) DANS LE PATH PYTHON
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
from scrapers.utils import score_candidate

# Désactivation des logs verbeux
logging.basicConfig(level=logging.ERROR)

print("=================================================================")
print("🧪 STRESS-TEST D'ÉVALUATION DE SCORING (20 CAS LIMITES)")
print("=================================================================\n")

TEST_SUITE = [
    # --- CATÉGORIE 1 : NUMÉROTATION ET VOLUMES ---
    {
        "name": "1. Chiffres Romains (Tome II vs Tome 2)",
        "query": "Astérix Tome II",
        "context": {"isbn": None, "authors": ["Uderzo", "Goscinny"]},
        "candidate": {"title": "Astérix, Tome 2 : Astérix et la Serpe d'or", "staff": [{"node": {"name": {"full": "René Goscinny"}}}, {"node": {"name": {"full": "Albert Uderzo"}}}]},
        "target": "PASS", # Doit passer (> 60%)
        "explain": "Détection de tome identique malgré l'écriture en Chiffre Romain."
    },
    {
        "name": "2. Recherche spécifique de Tome X (Match exact)",
        "query": "Dune Tome 2",
        "context": {"isbn": None, "authors": ["Frank Herbert"]},
        "candidate": {"title": "Dune, Tome 2 : Le Messie de Dune", "staff": [{"node": {"name": {"full": "Frank Herbert"}}}]},
        "target": "PASS",
        "explain": "Match parfait sur le tome spécifiquement recherché."
    },
    {
        "name": "3. Recherche spécifique de Tome X (Conflit de Tome)",
        "query": "Dune Tome 2",
        "context": {"isbn": None, "authors": ["Frank Herbert"]},
        "candidate": {"title": "Dune, Tome 1 : Dune", "staff": [{"node": {"name": {"full": "Frank Herbert"}}}]},
        "target": "FAIL", # Doit échouer (< 60%)
        "explain": "On cherchait le T2, le T1 doit être rejeté pour éviter de mélanger les tomes."
    },
    {
        "name": "4. Zéro à gauche (One Piece 01 vs Tome 1)",
        "query": "One Piece 01",
        "context": {"isbn": None, "authors": ["Eiichiro Oda"]},
        "candidate": {"title": "One Piece - Tome 1", "staff": [{"node": {"name": {"full": "Eiichiro Oda"}}}]},
        "target": "PASS",
        "explain": "Reconnaissance de '01' comme étant le Tome 1."
    },
    {
        "name": "5. Sous-titre de Volume en anglais (Book One)",
        "query": "Harleen",
        "context": {"isbn": None, "authors": ["Stjepan Sejic"]},
        "candidate": {"title": "Harleen: Book One", "staff": [{"node": {"name": {"full": "Stjepan Sejic"}}}]},
        "target": "PASS",
        "explain": "Application du bonus de Tome 1 pour une série globale."
    },

    # --- CATÉGORIE 2 : SPIN-OFFS, GUIDEBOOKS ET ÉDITIONS ---
    {
        "name": "6. Piège du Spin-Off / Saga Dérivée",
        "query": "Lanfeust de Troy",
        "context": {"isbn": None, "authors": ["Arleston"]},
        "candidate": {"title": "Lanfeust des Étoiles - Tome 1", "staff": [{"node": {"name": {"full": "Arleston"}}}]},
        "target": "FAIL",
        "explain": "Lanfeust des Étoiles est une série dérivée, elle ne doit PAS écraser Lanfeust de Troy."
    },
    {
        "name": "7. Piège du Guidebook / Fanbook",
        "query": "Berserk",
        "context": {"isbn": None, "authors": ["Kentaro Miura"]},
        "candidate": {"title": "Berserk Official Guidebook", "staff": [{"node": {"name": {"full": "Kentaro Miura"}}}]},
        "target": "FAIL",
        "explain": "Le guidebook ne doit pas être retenu comme la fiche du manga principal."
    },
    {
        "name": "8. Édition Spéciale / Deluxe / Perfect",
        "query": "Monster",
        "context": {"isbn": None, "authors": ["Naoki Urasawa"]},
        "candidate": {"title": "Monster - Perfect Edition Tome 1", "staff": [{"node": {"name": {"full": "Naoki Urasawa"}}}]},
        "target": "PASS",
        "explain": "Une édition 'Perfect' de la même œuvre reste la bonne œuvre."
    },

    # --- CATÉGORIE 3 : FORMATAGE ISBN ET DONNÉES INCOMPLÈTES ---
    {
        "name": "9. ISBN avec Tirets vs sans Tirets",
        "query": "Dune",
        "context": {"isbn": "978-2-266-22874-4", "authors": []},
        "candidate": {"title": "Dune", "isbn": "9782266228744", "staff": []},
        "target": "PASS",
        "explain": "L'ISBN doit valider à 100% quelle que soit la présence de tirets/espaces."
    },
    {
        "name": "10. Kavita SANS Auteurs (Recherche Brute)",
        "query": "Chainsaw Man",
        "context": {"isbn": None, "authors": []},
        "candidate": {"title": "Chainsaw Man", "staff": [{"node": {"name": {"full": "Tatsuki Fujimoto"}}}]},
        "target": "PASS",
        "explain": "Si Kavita n'a pas encore d'auteur, la recherche par titre seul doit fonctionner."
    },
    {
        "name": "11. Candidat SANS Staff/Auteur (API pauvre)",
        "query": "Fondation",
        "context": {"isbn": None, "authors": ["Isaac Asimov"]},
        "candidate": {"title": "Fondation", "staff": []},
        "target": "PASS",
        "explain": "Si l'API n'a pas renvoyé le staff, on ne pénalise pas (60% sur le titre)."
    },

    # --- CATÉGORIE 4 : NOMS D'AUTEURS ET ADAPTATIONS ---
    {
        "name": "12. Inversion Nom / Prénom (Urasawa Naoki)",
        "query": "20th Century Boys",
        "context": {"isbn": None, "authors": ["Urasawa Naoki"]},
        "candidate": {"title": "20th Century Boys", "staff": [{"node": {"name": {"full": "Naoki Urasawa"}}}]},
        "target": "PASS",
        "explain": "Reconnaissance de l'auteur malgré l'inversion Nom/Prénom."
    },
    {
        "name": "13. Auteurs Multiples / Duo d'Auteurs",
        "query": "Les Montagnes Hallucinées",
        "context": {"isbn": None, "authors": ["H.P. Lovecraft"]},
        "candidate": {"title": "Les Montagnes Hallucinées", "staff": [{"node": {"name": {"full": "Gou Tanabe"}}}, {"node": {"name": {"full": "H.P. Lovecraft"}}}]},
        "target": "PASS",
        "explain": "Validé car Lovecraft est bien présent dans la liste des auteurs du candidat."
    },
    {
        "name": "14. Titre très court (Risque Faux Positif)",
        "query": "Monster",
        "context": {"isbn": None, "authors": ["Naoki Urasawa"]},
        "candidate": {"title": "Monster Musume", "staff": [{"node": {"name": {"full": "OKAYADO"}}}]},
        "target": "FAIL",
        "explain": "Titre similaire mais Auteur différent = Rejet strict grâce à l'anti-homonyme."
    },

    # --- CATÉGORIE 5 : ARTICLES, SOUS-TITRES ET TITRES LOCALISÉS ---
    {
        "name": "15. Articles au début (The vs Le)",
        "query": "The Witcher",
        "context": {"isbn": None, "authors": ["Andrzej Sapkowski"]},
        "candidate": {"title": "Witcher (Le)", "staff": [{"node": {"name": {"full": "Andrzej Sapkowski"}}}]},
        "target": "PASS",
        "explain": "Match validé malgré la position de l'article."
    },
    {
        "name": "16. Titre avec Sous-titre long",
        "query": "Sapiens",
        "context": {"isbn": None, "authors": ["Yuval Noah Harari"]},
        "candidate": {"title": "Sapiens : Une brève histoire de l'humanité", "staff": [{"node": {"name": {"full": "Yuval Noah Harari"}}}]},
        "target": "PASS",
        "explain": "Validé car la série mère 'Sapiens' est le préfixe exact."
    },
    {
        "name": "17. Écart d'Année important (Réédition)",
        "query": "Watchmen",
        "context": {"isbn": None, "authors": ["Alan Moore"], "year": 1986},
        "candidate": {"title": "Watchmen", "staff": [{"node": {"name": {"full": "Alan Moore"}}}], "year": 2019},
        "target": "PASS",
        "explain": "L'année est subsidiaire quand le titre et l'auteur sont identiques à 100%."
    },
    {
        "name": "18. Homonyme Univers Différents (Avatar)",
        "query": "Avatar",
        "context": {"isbn": None, "authors": ["James Cameron"]},
        "candidate": {"title": "Avatar: The Last Airbender", "staff": [{"node": {"name": {"full": "Gene Luen Yang"}}}]},
        "target": "FAIL",
        "explain": "Rejeté car l'univers et l'auteur (James Cameron vs Gene Luen Yang) diffèrent."
    },
    {
        "name": "19. Ancrage via Titre Localisé Kavita",
        "query": "Shingeki no Kyojin",
        "context": {"isbn": None, "authors": ["Hajime Isayama"], "localized_name": "L'Attaque des Titans"},
        "candidate": {"title": "L'Attaque des Titans - Tome 1", "staff": [{"node": {"name": {"full": "Hajime Isayama"}}}]},
        "target": "PASS",
        "explain": "Validé car le candidat correspond au localized_name 'L'Attaque des Titans' stocké dans Kavita."
    },
    {
        "name": "20. Erreur d'Auteur Incomplet (Initiales vs Nom Complet)",
        "query": "Fondation",
        "context": {"isbn": None, "authors": ["I. Asimov"]},
        "candidate": {"title": "Fondation", "staff": [{"node": {"name": {"full": "Isaac Asimov"}}}]},
        "target": "PASS",
        "explain": "La similarité d'auteur doit réussir à lier 'I. Asimov' avec 'Isaac Asimov'."
    }
]

def run_suite():
    passed_tests = 0
    failed_tests = 0

    for test in TEST_SUITE:
        score = score_candidate(test["candidate"], test["query"], test["context"])
        score_pct = score * 100
        
        # Le seuil standard de validation dans MetaKavita est >= 60% (0.60)
        is_pass = score >= 0.60
        expected_pass = test["target"] == "PASS"
        
        success = (is_pass == expected_pass)
        
        if success:
            passed_tests += 1
            status_symbol = "\033[92m[RÉUSSI]\033[0m"
        else:
            failed_tests += 1
            status_symbol = "\033[91m[ÉCHEC]\033[0m"

        print(f"{status_symbol} {test['name']}")
        print(f"   Score Obtenu : {score_pct:.1f}% | Attendu : {'>= 60%' if expected_pass else '< 60%'}")
        if not success:
            print(f"   ⚠️ \033[93mAnomalie détectée\033[0m : {test['explain']}")
        print()

    print("-" * 65)
    print(f"📊 Bilan du Stress-Test : \033[92m{passed_tests} Réussis\033[0m | \033[91m{failed_tests} À Ajuster\033[0m")
    print("=================================================================\n")

if __name__ == "__main__":
    run_suite()