from app.models.room import Session
from flask.views import MethodView
from flask.globals import current_app
from flask_smorest.error_handler import ErrorSchema
from werkzeug.exceptions import NotAcceptable, NotFound, UnprocessableEntity

from app.models import Room
from app.extensions.api import Blueprint, abort
from app.views.api.openvidu.schemas import ConfigSchema, SignalSchema, SessionSchema, WebRtcConnectionSchema


blp = Blueprint('OpenVidu', __name__)


@blp.route('/config')
class Config(MethodView):
    @blp.response(200, ConfigSchema.Response)
    @blp.login_required
    def get(self):
        """ Retrieve current OpenVidu configuration

        See the <a href="https://docs.openvidu.io/en/2.18.0/reference-docs/openvidu-config/">
        OpenVidu documentation</a> on how to change these values.

        Only available if OpenVidu is enabled."""

        config = current_app.openvidu.config
        return dict(
            version=config['VERSION'],
            domain_or_public_ip=config['DOMAIN_OR_PUBLIC_IP'],
            https_port=config['HTTPS_PORT'],
            public_url=config['OPENVIDU_PUBLICURL'],
            cdr=config["OPENVIDU_CDR"],
            streams=dict(
                videoMinSendBandwidth=config['OPENVIDU_STREAMS_VIDEO_MIN_SEND_BANDWIDTH'],
                videoMaxSendBandwidth=config['OPENVIDU_STREAMS_VIDEO_MAX_SEND_BANDWIDTH'],
                videoMinRecvBandwidth=config['OPENVIDU_STREAMS_VIDEO_MIN_RECV_BANDWIDTH'],
                videoMaxRecvBandwidth=config['OPENVIDU_STREAMS_VIDEO_MAX_RECV_BANDWIDTH'],
            ),
            sessions=dict(
                garbage_interval=config['OPENVIDU_SESSIONS_GARBAGE_INTERVAL'],
                garbage_threshold=config['OPENVIDU_SESSIONS_GARBAGE_THRESHOLD'],
            ),
            recording=dict(
                version=config['OPENVIDU_RECORDING_VERSION'],
                path=config['OPENVIDU_RECORDING_PATH'],
                public_access=config['OPENVIDU_RECORDING_PUBLIC_ACCESS'],
                notification=config['OPENVIDU_RECORDING_NOTIFICATION'],
                custom_layout=config['OPENVIDU_RECORDING_CUSTOM_LAYOUT'],
                autostop_timeout=config['OPENVIDU_RECORDING_AUTOSTOP_TIMEOUT'],
            ) if config['OPENVIDU_RECORDING'] else None,
            webhook=dict(
                endpoint=config['OPENVIDU_WEBHOOK_ENDPOINT'],
                headers=config['OPENVIDU_WEBHOOK_HEADERS'],
                events=config['OPENVIDU_WEBHOOK_EVENTS'],
            ) if config['OPENVIDU_WEBHOOK'] else None
        )


@blp.route('sessions')
class Sessions(MethodView):
    @blp.response(200, SessionSchema.Response(many=True))
    @blp.login_required
    def get(self):
        """Retrieve all Session from OpenVidu Server

        Only available if OpenVidu is enabled."""

        response = current_app.openvidu.list_sessions()

        if response.status_code == 200:
            return response.json()['content']
        abort(response)

    @blp.arguments(SessionSchema.Creation, example={})
    @blp.alt_response(409, None)
    @blp.response(200, SessionSchema.Response)
    @blp.login_required
    def post(self, args):
        """Initialize a Session in OpenVidu Server

        This is the very first operation to perform in OpenVidu workflow. After that,
        Connection objects can be generated for this Session and their token passed
        to the client-side, so clients can use it to connect to the Session.

        Only available if OpenVidu is enabled."""

        response = current_app.openvidu.post_session(args)

        if response.status_code == 200:
            session = response.json()
            current_app.logger.info(f'Created new session `{session["id"]}`')

            # Store session parameters in database to recreate it if necessary
            db = current_app.session
            db.add(Session(id=session['id'], parameters=args))
            db.commit()
            return session
        elif response.status_code == 400:
            abort(UnprocessableEntity, json=response.json().get('message'))
        abort(response)


@blp.route('sessions/<string:session_id>')
class SessionsById(MethodView):
    @blp.response(200, SessionSchema.Response)
    @blp.alt_response(404, ErrorSchema)
    @blp.login_required
    def get(self, *, session_id):
        """Retrieve a Session from OpenVidu Server

        Only available if OpenVidu is enabled."""
        response = current_app.openvidu.get_session(session_id)

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            abort(NotFound, query=f'Session `{session_id}` does not exist')
        abort(response)

    @blp.response(204)
    @blp.alt_response(404, ErrorSchema)
    @blp.alt_response(406, ErrorSchema)
    @blp.login_required
    def delete(self, *, session_id):
        """Close a Session

        This will stop all of the processes of this Session: all of its Connections,
        Streams and Recordings will be closed.

        Only available if OpenVidu is enabled."""

        if current_app.session.query(Room).filter_by(session=session_id).count() > 0:
            abort(NotAcceptable, query=f'Session `{session_id}` is still in use')

        response = current_app.openvidu.delete_session(session_id)

        if response.status_code == 204:
            return
        elif response.status_code == 404:
            abort(NotFound, query=f'Session `{session_id}` does not exist')
        abort(response)


@blp.route('sessions/<string:session_id>/signal')
class SessionsSignal(MethodView):
    @blp.arguments(SignalSchema.Creation)
    @blp.response(204)
    @blp.alt_response(404, ErrorSchema)
    @blp.alt_response(406, ErrorSchema)
    @blp.alt_response(422, ErrorSchema)
    @blp.login_required
    def post(self, args, *, session_id):
        """Send a signal to a Session, to specific Connections or as a broadcast message to all Connections.

        This is the server-side implementation of the client operation Session.signal.

        Only available if OpenVidu is enabled."""

        response = current_app.openvidu.signal(session_id, args)

        if response.status_code == 200:
            return
        elif response.status_code == 400:
            abort(UnprocessableEntity, json=response.json().get('message'))
        elif response.status_code == 404:
            abort(NotFound, query=f'Session `{session_id}` does not exist')
        elif response.status_code == 406:
            abort(NotAcceptable, json=f'No connection exists for the passed to array. This error may be triggered if the session has no connected participants or if you provide some string value that does not correspond to a valid connectionId of the session (even though others may be correct)')
        abort(response)


@blp.route('sessions/<string:session_id>/connections')
class Connection(MethodView):
    @blp.response(200, WebRtcConnectionSchema.Response(many=True))
    @blp.alt_response(404, ErrorSchema)
    @blp.login_required
    def get(self, *, session_id):
        """List all Connections from a Session

        Only available if OpenVidu is enabled."""

        response = current_app.openvidu.list_connections(session_id)

        if response.status_code == 200:
            return response.json()['content']
        elif response.status_code == 404:
            abort(NotFound, query=f'Session `{session_id}` does not exist')
        abort(response)

    @blp.arguments(WebRtcConnectionSchema.Creation, example={})
    @blp.response(200, WebRtcConnectionSchema.Response)
    @blp.alt_response(404, ErrorSchema)
    @blp.login_required
    def post(self, args, *, session_id):
        """Create a new Connection in the Session

        Only available if OpenVidu is enabled."""

        response = current_app.openvidu.post_connection(session_id, args)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 400:
            abort(UnprocessableEntity, json=response.json().get('message'))
        elif response.status_code == 404:
            abort(NotFound, query=f'Session `{session_id}` does not exist')
        abort(response)


@blp.route('sessions/<string:session_id>/connections/<string:connection_id>')
class ConnectionById(MethodView):
    @blp.response(200, WebRtcConnectionSchema.Response)
    @blp.alt_response(404, ErrorSchema)
    @blp.login_required
    def get(self, *, session_id, connection_id):
        """Get a Connection from a Session

        Only available if OpenVidu is enabled."""

        response = current_app.openvidu.get_connection(session_id, connection_id)

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 400:
            abort(NotFound, query=f'Session `{session_id}` does not exist')
        elif response.status_code == 404:
            abort(NotFound, query=f'Connection `{connection_id}` does not exist')
        abort(response)

    @blp.response(204)
    @blp.alt_response(404, ErrorSchema)
    @blp.login_required
    def delete(self, *, session_id, connection_id):
        """Force the disconnection of a user from a Session

        All of the streams associated to this Connection (both publishers and subscribers) will
        be destroyed. If the user was publishing a stream, all other subscribers of other users
        receiving it will also be destroyed.

        If the connection_id belongs to a Connection in pending status, this method will simply
        invalidate it (its token will be no longer available for any user to connect to the Session).

        Only available if OpenVidu is enabled."""

        response = current_app.openvidu.delete_connection(session_id, connection_id)
        if response.status_code == 204:
            return
        elif response.status_code == 400:
            abort(NotFound, query=f'Session `{session_id}` does not exist')
        elif response.status_code == 404:
            abort(NotFound, query=f'Connection `{connection_id}` does not exist')
        abort(response)
