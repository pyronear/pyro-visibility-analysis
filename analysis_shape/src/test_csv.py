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

def write_csv(filename, colonne_name, values):
    """Ajoute des colonnes spécifiées dans le fichier CSV, sans perdre les lignes existantes."""
    try:
        # Lire le fichier CSV source pour récupérer les données existantes
        with open(filename, mode="r", newline="", encoding="utf-8") as file:
            reader = csv.reader(file, delimiter=";")
            rows = list(reader)  # Lire toutes les lignes du fichier
            header = rows[0]  # L'en-tête (première ligne)

            # Ajouter les nouvelles colonnes spécifiées à l'en-tête
            header.extend(colonne_name)

            # Ajouter les nouvelles colonnes à chaque ligne existante
            for row in rows[1:]:  # Ignorer la première ligne (en-tête)
                nom = row[0]  # On suppose que le 'Nom' est dans la première colonne
                # Vérifier si le 'nom' est présent dans le dictionnaire de valeurs
                if nom in values:
                    row.extend(values[nom])  # Ajouter la valeur correspondante pour ce nom
                else:
                    # Ajouter une valeur vide si le nom n'est pas trouvé dans le dictionnaire
                    row.extend([''] * len(colonne_name))

        # Ouvrir le fichier en mode écriture pour ajouter les colonnes
        with open(filename, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file, delimiter=";")
            writer.writerow(header)  # Réécrire l'en-tête avec les nouvelles colonnes
            writer.writerows(rows[1:])  # Réécrire les lignes de données existantes avec les nouvelles colonnes

        print(f"✅ Colonnes {colonne_name} ajoutées au fichier : {filename}")

    except Exception as e:
        print(f"❌ Erreur lors de l'ajout des colonnes : {e}")


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
    "Barr": [8]
    }
    write_csv(fichier, ["remplissage"], test)
    # Ouvrir le fichier avec Excel et attendre sa fermeture

    open_excel(fichier)
    

if __name__ == "__main__":
    main()