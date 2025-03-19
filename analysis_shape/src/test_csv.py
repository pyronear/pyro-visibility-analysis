import csv
import os
import subprocess

PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DATA_PATH = os.path.join(PATH, "data")
CSV_PATH = os.path.join(DATA_PATH, "pts_hauts_2.csv")

def create_csv(path, filename):
    """Lit un fichier CSV, extrait certaines colonnes et les écrit dans un nouveau fichier CSV avec des valeurs pour chaque ligne."""
    try:
        # Lire le fichier CSV source en utilisant ; comme délimiteur
        with open(path, mode="r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file, delimiter=";")  # Spécifier le délimiteur ici
            # Colonnes recherchées
            colonnes_voulues = ["Nom", "Latitude", "Longitude", "Hauteur (m)"]  # Mettre le nom exact de la colonne

            # Créer un fichier CSV de destination avec ; comme délimiteur
            with open(filename, mode="w", newline="", encoding="utf-8") as new_file:
                writer = csv.writer(new_file, delimiter=";")  # Utiliser un point-virgule aussi pour le fichier destination
                # Écrire l'en-tête
                writer.writerow(colonnes_voulues)
                # Pour chaque ligne, filtrer et écrire les données des colonnes voulues
                for row in list(reader):
                    # Extraire uniquement les colonnes présentes dans le fichier source
                    ligne = [row[col] for col in row if col in colonnes_voulues]
                    writer.writerow(ligne)

        print(f"✅ Fichier créé avec les colonnes filtrées et les valeurs : {filename}")
    except Exception as e:
        print(f"❌ Erreur lors de la lecture ou de l'écriture du fichier : {e}")

import csv

def write_csv(filename, dict_values):
    """Ajoute des colonnes spécifiées dans le fichier CSV, sans perdre les lignes existantes."""
    try:
        # Lire le fichier CSV source pour récupérer les données existantes
        with open(filename, mode="r", newline="", encoding="utf-8") as file:
            reader = csv.reader(file, delimiter=";")
            rows = list(reader)  # Lire toutes les lignes du fichier
            header = rows[0]  # L'en-tête (première ligne)

            # Récupérer dynamiquement les nouvelles colonnes à ajouter
            keys = list(next(iter(dict_values.values())).keys())  
            
            # Vérifier et ajouter les nouvelles colonnes à l'en-tête si elles n'existent pas
            existing_columns = set(header)
            new_columns = [col for col in keys if col not in existing_columns]
            header.extend(new_columns)

            # Créer une nouvelle liste de lignes avec les valeurs mises à jour
            updated_rows = [header]  

            for row in rows[1:]:  # Ignorer l'en-tête
                nom = row[0]  # Supposons que le 'Nom' est dans la première colonne
                
                # Récupérer les valeurs de dict_values ou remplir avec des valeurs vides
                values_to_add = [str(dict_values[nom][col]) if nom in dict_values else '' for col in keys]

                # Compléter la ligne avec des valeurs vides si elle était plus courte que l'en-tête
                row.extend([''] * (len(header) - len(row)))

                # Ajouter les nouvelles valeurs aux bonnes colonnes
                for i, col in enumerate(keys):
                    row[header.index(col)] = values_to_add[i]

                updated_rows.append(row)

        # Ouvrir le fichier en mode écriture pour enregistrer les changements
        with open(filename, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file, delimiter=";")
            writer.writerows(updated_rows)  # Écrire toutes les lignes (header + données mises à jour)

        print(f"✅ Colonnes {new_columns} ajoutées et fichier mis à jour : {filename}")

    except Exception as e:
        print(f"❌ Erreur lors de la mise à jour du fichier CSV : {e}")


def open_excel_and_process(filename):
    """Ouvre le fichier CSV directement avec excel.exe et attend sa fermeture."""
    filepath = os.path.abspath(filename)
    try:
        print(f"📂 Tentative d'ouverture avec Excel : {filepath}")

        # Vérifier si Excel est bien installé
        excel_path = r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE"  # Modifier si nécessaire
        if not os.path.exists(excel_path):
            excel_path = r"C:\Program Files (x86)\Microsoft Office\root\Office16\EXCEL.EXE"  # Version 32 bits
        if not os.path.exists(excel_path):
            print("⚠️ Excel introuvable, vérifiez son installation.")
            return

        # Lancer Excel en lui passant le fichier CSV
        process = subprocess.Popen([excel_path, filepath])
        process.wait()  # Attend la fermeture de l'application

        print(f"✅ Le fichier {filename} a été fermé.")
        check()
    except Exception as e:
        print(f"❌ Erreur lors de l'ouverture du fichier : {e}")

def check():
    """Fonction exécutée après la fermeture d'Excel."""
    print("🔍 Vérification : Tout est OK !")

def open_excel(filename):
    """Ouvre le fichier CSV directement avec Excel sans attendre sa fermeture."""
    filepath = os.path.abspath(filename)
    try:
        print(f"📂 Tentative d'ouverture avec Excel : {filepath}")

        # Vérifier si Excel est bien installé
        excel_path = r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE"  # Modifier si nécessaire
        if not os.path.exists(excel_path):
            excel_path = r"C:\Program Files (x86)\Microsoft Office\root\Office16\EXCEL.EXE"  # Version 32 bits
        if not os.path.exists(excel_path):
            print("⚠️ Excel introuvable, vérifiez son installation.")
            return

        # Lancer Excel en lui passant le fichier CSV sans attendre la fermeture
        subprocess.Popen([excel_path, filepath])

        print(f"✅ Le fichier {filename} a été ouvert dans Excel.")
    except Exception as e:
        print(f"❌ Erreur lors de l'ouverture du fichier : {e}")




def main():
    fichier = "mon_fichier.csv"

    # Création du fichier avec en-têtes
    create_csv(CSV_PATH, fichier)

    open_excel_and_process(fichier)

    test = {
    "Benfeld": {"surface": 12345, "p_surface": 0.75, "r_surface": 0.50},
    "Strasbourg": {"surface": 67890, "p_surface": 0.85, "r_surface": 0.60}}

    write_csv(fichier, test)
    # Ouvrir le fichier avec Excel et attendre sa fermeture

    open_excel(fichier)
    

if __name__ == "__main__":
    main()