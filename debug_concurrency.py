#!/usr/bin/env python3
"""
Script de débogage 100% STANDALONE pour MetaKavita (Problème d'écrasement de couverture).
N'utilise STRICTEMENT AUCUNE bibliothèque tierce (ni Flask, ni Eventlet, ni requests).
Fonctionne directement avec le Python système de ton serveur hôte.
"""

import os
import sys
import sqlite3
import time
import threading

# Import sécurisé du db_manager local (qui utilise uniquement sqlite3 natif)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from db_manager import init_db, get_all_cached_data, save_forced_overrides, update_status
except Exception as e:
    print(f"❌ Impossible d'importer db_manager: {e}")
    sys.exit(1)


class MockKavitaServer:
    """Simule le serveur Kavita et l'image de couverture réellement enregistrée."""
    def __init__(self):
        self.covers = {}
        self.lock = threading.Lock()

    def upload_series_cover(self, series_id, cover_data):
        with self.lock:
            self.covers[series_id] = cover_data
            print(f"   [KAVITA SERVER] 🖼️ Image enregistrée sur le disque pour ID {series_id} -> '{cover_data}'")
            return True, "OK"

    def get_cover(self, series_id):
        with self.lock:
            return self.covers.get(series_id)


def simulate_app_apply_series_cover_CURRENT(kavita_mock, series_id, new_cover_url):
    """
    CODE ACTUEL dans app.py (/api/series/<id>/update-cover) :
    Upload direct vers Kavita SANS mettre à jour la base de données local (cache.db) !
    """
    print(f"\n👉 [ACTION UTILISATEUR] Upload manuel de la couverture : '{new_cover_url}'")
    kavita_mock.upload_series_cover(series_id, new_cover_url)


def simulate_app_apply_series_cover_FIXED(kavita_mock, series_id, new_cover_url):
    """
    CODE CORRIGÉ :
    Upload vers Kavita ET suppression automatique du champ 'cover' dans targeted_fields !
    """
    print(f"\n👉 [ACTION UTILISATEUR (CORRIGÉE)] Upload manuel : '{new_cover_url}'")
    success, msg = kavita_mock.upload_series_cover(series_id, new_cover_url)
    if success:
        cache_data = get_all_cached_data().get(int(series_id), {})
        forced_id = cache_data.get('forced_id', '') or ''
        alt_title = cache_data.get('alternative_title', '') or ''
        forced_provider = cache_data.get('forced_provider', 'AUTO') or 'AUTO'
        
        current_fields = cache_data.get('targeted_fields', 'ALL') or 'ALL'
        if current_fields == 'ALL':
            all_fields = ['summary', 'staff', 'genres', 'tags', 'year', 'status', 'publisher', 'age', 'format', 'weblinks', 'alt_titles']
        else:
            all_fields = [f for f in current_fields.split(',') if f != 'cover']
            
        new_targeted_fields = ",".join(all_fields)
        save_forced_overrides(int(series_id), forced_id, alt_title, forced_provider, new_targeted_fields)
        print(f"   [DB FIX] 🔒 Champ 'cover' retiré de targeted_fields (Nouveaux champs autorisés: '{new_targeted_fields}')")


def simulate_process_series_logic(kavita_mock, series_id, provider_cover_url, global_auto_cover=True):
    """
    Simule la logique de scraping/batch de app.py (process_series_logic).
    """
    print(f"\n🔄 [WORKER / BATCH] Lancement du scraping automatique sur la série {series_id}...")
    
    cache_data = get_all_cached_data().get(int(series_id), {})
    targeted_fields_raw = cache_data.get('targeted_fields', 'ALL') or 'ALL'
    
    if targeted_fields_raw == 'ALL':
        active_fields = ['summary', 'cover', 'staff', 'genres', 'tags', 'year', 'status', 'publisher', 'age', 'format', 'weblinks', 'alt_titles']
    else:
        active_fields = targeted_fields_raw.split(',')

    print(f"   [WORKER] Champs autorisés dans cache.db : {active_fields}")

    # Condition exacte de app.py :
    if 'cover' in active_fields and global_auto_cover and provider_cover_url:
        print(f"   [WORKER] 'cover' est présent + AUTO_COVER=True -> Envoi de la couverture du scraper ('{provider_cover_url}')...")
        kavita_mock.upload_series_cover(series_id, provider_cover_url)
    else:
        print(f"   [WORKER] ⏭️ ÉTAPE COUVERTURE IGNORÉE ! ('cover' est désactivé ou verrouillé).")


def run_tests():
    print("="*65)
    print("🧪 TEST STANDALONE METAKAVITA - DIAGNOSTIC D'ÉCRASEMENT")
    print("="*65)

    init_db()
    test_series_id = 88888
    update_status(test_series_id, "PENDING")
    save_forced_overrides(test_series_id, "", "", "AUTO", "ALL")

    kavita = MockKavitaServer()

    # -------------------------------------------------------------
    # SCÉNARIO 1 : DÉMONSTRATION DU BUG
    # -------------------------------------------------------------
    print("\n" + "─"*65)
    print("🚨 SCÉNARIO 1 : REPRODUCTION DU BUG (Code Actuel dans MetaKavita)")
    print("─"*65)

    # 1. Scraping auto initial
    simulate_process_series_logic(kavita, test_series_id, "http://provider.com/cover_manga.jpg", global_auto_cover=True)
    print(f"   -> Image dans Kavita : '{kavita.get_cover(test_series_id)}'")

    # 2. L'utilisateur remplace la couverture manuellement dans l'UI
    simulate_app_apply_series_cover_CURRENT(kavita, test_series_id, "http://mon-choix-perso.com/belle_couverture.jpg")
    print(f"   -> Image dans Kavita : '{kavita.get_cover(test_series_id)}'")

    # 3. Un Auto-Sync ou un Batch est relancé plus tard
    simulate_process_series_logic(kavita, test_series_id, "http://provider.com/cover_manga.jpg", global_auto_cover=True)
    final_cover_1 = kavita.get_cover(test_series_id)

    if final_cover_1 == "http://provider.com/cover_manga.jpg":
        print("\n❌ [BUG CONFIRMÉ] La couverture choisie par l'utilisateur a été ÉCRASÉE par le batch suivant !")

    # -------------------------------------------------------------
    # SCÉNARIO 2 : AVEC LE CORRECTIF
    # -------------------------------------------------------------
    print("\n" + "─"*65)
    print("✅ SCÉNARIO 2 : TEST AVEC LE CORRECTIF DANS APP.PY")
    print("─"*65)

    # Reset
    save_forced_overrides(test_series_id, "", "", "AUTO", "ALL")

    # 1. Scraping auto initial
    simulate_process_series_logic(kavita, test_series_id, "http://provider.com/cover_manga.jpg", global_auto_cover=True)

    # 2. L'utilisateur remplace la couverture (avec le FIX)
    simulate_app_apply_series_cover_FIXED(kavita, test_series_id, "http://mon-choix-perso.com/belle_couverture.jpg")

    # 3. Un Auto-Sync ou un Batch est relancé
    simulate_process_series_logic(kavita, test_series_id, "http://provider.com/cover_manga.jpg", global_auto_cover=True)
    final_cover_2 = kavita.get_cover(test_series_id)

    if final_cover_2 == "http://mon-choix-perso.com/belle_couverture.jpg":
        print("\n🎉 [PROBLÈME RÉSOLU] La couverture choisie par l'utilisateur est CONSERVÉE et PROTÉGÉE !")

    # -------------------------------------------------------------
    # SCÉNARIO 3 : SIMULATION DE RACE CONDITION (Concurrence simultanée)
    # -------------------------------------------------------------
    print("\n" + "─"*65)
    print("⚡ SCÉNARIO 3 : SIMULATION DE CONCURRENCE (Rivalité de Threads)")
    print("─"*65)

    save_forced_overrides(test_series_id, "", "", "AUTO", "ALL")
    race_kavita = MockKavitaServer()

    def slow_batch_worker():
        print("  [Thread Batch] Lecture de targeted_fields dans la DB (vaut 'ALL')...")
        time.sleep(0.3)  # Simule le délai du scraper distant (réseau)
        print("  [Thread Batch] Scraper terminé. Envoi de la couverture du scraper...")
        race_kavita.upload_series_cover(test_series_id, "http://provider.com/slow_batch_cover.jpg")

    def user_click():
        time.sleep(0.1)  # Clic de l'utilisateur PENDANT que le batch tourne
        print("  [Thread User] Clic utilisateur 'Appliquer la couverture'...")
        simulate_app_apply_series_cover_FIXED(race_kavita, test_series_id, "http://user.com/fast_user_cover.jpg")

    t1 = threading.Thread(target=slow_batch_worker)
    t2 = threading.Thread(target=user_click)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    final_race_cover = race_kavita.get_cover(test_series_id)
    print(f"\n📌 Image finale dans Kavita après concurrence : '{final_race_cover}'")
    if final_race_cover == "http://provider.com/slow_batch_cover.jpg":
        print("⚠️ [RACE CONDITION CONFIRMÉE] Le worker ayant lu la DB avant le clic a terminé après le clic et l'a écrasé !")

    print("\n" + "="*65)

if __name__ == "__main__":
    run_tests()