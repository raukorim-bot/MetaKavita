#!/bin/bash

echo "🚀 Initialisation de l'environnement pour MetaKavita..."
echo "--------------------------------------------------------"

if [ ! -f metakavita.log ]; then
    touch metakavita.log
    echo "✅ metakavita.log créé."
else
    echo "ℹ️ metakavita.log existe déjà."
fi

if [ ! -f cache.db ]; then
    touch cache.db
    echo "✅ cache.db créé."
else
    echo "ℹ️ cache.db existe déjà."
fi

if [ ! -f config.json ]; then
    echo "{}" > config.json
    echo "✅ config.json créé."
else
    echo "ℹ️ config.json existe déjà."
fi

echo "--------------------------------------------------------"
echo "🎉 Tout est prêt ! Tu peux maintenant démarrer le conteneur avec :"
echo "docker compose up --build -d"
