# -*- coding: utf-8 -*-
"""Sources d'horaires chargées par le moteur local (gtfs.py).

- « sncf » : export GTFS de la SNCF (TER, cars TER, Intercités ; identifiants de gares = codes UIC) ;
- les autres : réseaux régionaux de cars (et quelques trains) publiés en open data sur
  transport.data.gouv.fr. Ils comblent ce que le GTFS SNCF ne contient pas (ZOU!, liO, Aléop…).

Chaque entrée : identifiant court -> (URL de téléchargement, nom du réseau affiché).
Pour ajouter un réseau : trouver son jeu de données GTFS sur transport.data.gouv.fr et ajouter une ligne.
"""

DG = "https://www.data.gouv.fr/api/1/datasets/r/"
TDG = "https://transport.data.gouv.fr/resources/"

SNCF = ("https://eu.ftp.opendatasoft.com/sncf/plandata/Export_OpenData_SNCF_GTFS_NewTripId.zip", "SNCF")

REGIONAL = {
    # Provence-Alpes-Côte d'Azur
    "zou_express": (DG + "1164d75b-4a9f-4c5a-b765-31d861b34fda", "ZOU !"),
    "zou_proximite": (DG + "9c8116cb-2f1a-4045-b149-c5bf6cae6bef", "ZOU !"),
    "zou_trains_transdev": (DG + "764d6d5b-d04e-4aa7-94b7-f8b2274d2964", "ZOU !"),
    # Auvergne-Rhône-Alpes
    "aura_express": (DG + "c379471b-c554-4838-9c00-39d7ced7b53a", "Cars Région"),
    "aura_01": (DG + "723f0cc2-476a-464c-a40e-bf8686f7bd8d", "Cars Région"),
    "aura_03": (DG + "edf15063-dbbb-4543-a39d-60a39a418ee3", "Cars Région"),
    "aura_07": (DG + "4e69fff6-6ae5-4ac0-9fa4-9c24ac92f291", "Cars Région"),
    "aura_15": (DG + "2053f06d-439c-43fe-87fb-528179a8502e", "Cars Région"),
    "aura_26": (DG + "fda59af2-0eb3-4a8a-8e59-593f768f836a", "Cars Région"),
    "aura_38": (DG + "40ee9d6c-3bb9-409e-b670-986212de63f2", "Cars Région"),
    "aura_42": (DG + "d22ab458-e6b4-4334-96dc-18590a3d9e5d", "Cars Région"),
    "aura_43": (DG + "6dc48e22-edc4-478d-896d-7fdd02bbcda9", "Cars Région"),
    "aura_63": (DG + "fff9c08f-6172-4c94-b46e-c0144ae0bd10", "Cars Région"),
    "aura_73": (DG + "4b74f1b9-fcc0-4e59-bf48-7ed4102e5222", "Cars Région"),
    "aura_74": (DG + "71926816-92f8-4620-8b8f-e1804f645e26", "Cars Région"),
    # Occitanie
    "lio": (DG + "d747fe79-2915-4cdd-8cc5-51a810baaca5", "liO"),
    # Pays de la Loire, Bretagne, Normandie
    "aleop": (DG + "916752e4-5daa-48bd-8bc1-4dd8d64f1d4a", "Aléop"),
    "breizhgo_car": (DG + "1b9a895a-1843-4620-bcd4-3bbd08c396c0", "BreizhGo"),
    "nomad_car": (TDG + "82317/download", "Nomad"),
    # Bourgogne-Franche-Comté, Centre-Val de Loire, Grand Est
    "mobigo": (DG + "5c995d2c-8e79-4e40-b4a6-c0583c647201", "Mobigo"),
    "remi": (DG + "6c52238c-1c1e-4c5a-922b-8b66c0415a9e", "Rémi"),
    "fluo": (TDG + "83635/download", "Fluo"),
    # Nouvelle-Aquitaine (réseaux départementaux)
    "na_16": (DG + "7eb95c82-711e-455c-86b1-ecf138697ebe", "Cars Nouvelle-Aquitaine"),
    "na_17": (DG + "161ac8dd-bdd4-40dd-bce7-d9edef4af632", "Cars Nouvelle-Aquitaine"),
    "na_19": (DG + "2b76718b-2ab0-4f95-8528-cce4bb6af4fe", "Cars Nouvelle-Aquitaine"),
    "na_23": (DG + "b3f2f823-fe55-4265-9efe-605d8156dea2", "Cars Nouvelle-Aquitaine"),
    "na_24": (DG + "f7590323-d782-40ed-a6b2-67e37930f6cd", "Cars Nouvelle-Aquitaine"),
    "na_33": (DG + "ba4be162-cc7f-4c7c-9d96-376a225e9045", "Cars Nouvelle-Aquitaine"),
    "na_40": (DG + "476fec18-c51f-41e6-9d15-0030174389c3", "Cars Nouvelle-Aquitaine"),
    "na_47": (DG + "bbf7ffef-9706-42e8-a3c8-7113168621d7", "Cars Nouvelle-Aquitaine"),
    "na_64": (DG + "44806d1e-0798-40e6-8e7e-21d0ddfe81d2", "Cars Nouvelle-Aquitaine"),
    "na_79": (DG + "73b1b1ee-2b81-445f-8930-b95a2b28a81b", "Cars Nouvelle-Aquitaine"),
    "na_86": (DG + "a70fab11-9ac9-481e-91c8-925e805741ba", "Cars Nouvelle-Aquitaine"),
    "na_87": (DG + "8d1cc7f8-2b29-4844-b98c-4a5b35075d57", "Cars Nouvelle-Aquitaine"),
    # Hauts-de-France (réseaux départementaux)
    "hdf_02": (DG + "4258bcab-8da4-42fe-a811-0135d7476e85", "Cars Hauts-de-France"),
    "hdf_59": (DG + "293d12e7-7db8-42d8-bbb4-543aad13fc7e", "Cars Hauts-de-France"),
    "hdf_60": (DG + "67129a71-49d0-467d-b388-4672ab1d5593", "Cars Hauts-de-France"),
    "hdf_62": (DG + "3e744287-1221-47fd-96e0-fa154e79c4f8", "Cars Hauts-de-France"),
    "hdf_80": (DG + "429d30fb-ba6e-4e90-ad82-6d589a98cbfd", "Cars Hauts-de-France"),
    # Corse
    "corse_cars": (DG + "fe20cb23-34b8-4965-acf7-1b28bf966891", "Cars de Corse"),
    "corse_train": (DG + "69c3db8a-a5fd-471f-b59f-46b9faded381", "Chemins de fer de la Corse"),
}
