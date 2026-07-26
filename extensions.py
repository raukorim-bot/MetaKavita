"""
Instances d'extensions partagées entre app.py, routes/ et sockets/.

Isoler `socketio` ici (au lieu de le définir dans app.py) évite les imports
circulaires : routes/*.py et sockets/handlers.py ont besoin de l'instance
SocketIO pour émettre des événements ou déclarer des handlers `@socketio.on(...)`,
mais ne doivent pas avoir à importer app.py (qui, lui, importe routes/ et
sockets/ pour les enregistrer). `socketio.init_app(app)` est appelé une seule
fois dans app.py, une fois l'objet Flask `app` créé.
"""

from flask_socketio import SocketIO

socketio = SocketIO()
