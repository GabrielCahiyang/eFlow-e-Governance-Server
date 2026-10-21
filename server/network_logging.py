"""Keep routine polling quiet and classify Windows socket-close noise narrowly."""
import logging


class SuccessfulHealthPoll(logging.Filter):
    def filter(self, record):
        args = record.args
        return not (isinstance(args, tuple) and len(args) == 5
                    and args[2].split('?', 1)[0].rstrip('/') == '/controlpanelEflow/api/health'
                    and args[4] == 200)


def install_network_logging(loop):
    access = logging.getLogger('uvicorn.access')
    if not any(isinstance(item, SuccessfulHealthPoll) for item in access.filters):
        access.addFilter(SuccessfulHealthPoll())
    previous = loop.get_exception_handler()

    def handle(current_loop, context):
        exc = context.get('exception')
        callback = str(context.get('handle', ''))
        if isinstance(exc, ConnectionResetError) and getattr(exc, 'winerror', None) == 10054 and '_ProactorBasePipeTransport._call_connection_lost' in callback:
            logging.getLogger(__name__).debug('Peer disconnected while Windows closed its socket.')
            return
        if previous:
            previous(current_loop, context)
        else:
            current_loop.default_exception_handler(context)

    loop.set_exception_handler(handle)
    return previous
