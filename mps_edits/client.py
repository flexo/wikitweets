"""client.py - client for mps_edits"""
import os
import re
import sys
import getopt
import logging
import logging.config
import ConfigParser

import twitter # pip install python-twitter
from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from twisted.python import log as twisted_log

from . import config

log = logging.getLogger(__name__)

class EditsListener(irc.IRCClient):
    """IRC bot that listens to wikipedia edits."""
    # edit message looks like this:
    # u'\x0314[[\x0307Darin Erstad\x0314]]\x034 \x0310 \x0302http://en.wikipedia.org/w/index.php?diff=650841539&oldid=650491223\x03 \x035*\x03 \x0303Erik255\x03 \x035*\x03 (+2) \x0310\x03'
    edit_re = re.compile(
        r'^\x0314\[\[\x0307'    # <grey>[[<yellow>
        r'([^\x03]*)'           # Article name
        r'\x0314\]\]'           # <grey>]]
        r'\x034 \x0310 \x0302'  # <?><?><blue>
        r'([^\x03]*)'           # Diff URI
        r'\x03 \x035\*\x03 \x0303' # <red><literal *><green>
        r'([^\x03]*)'           # User name or IP address
    )
    ip_re = re.compile(
        r'^([0-9]{1,3}\.){3}[0-9]{1,3}$') # TODO - IPv6

    def __init__(self, cfg, twitter_api):
        self.nickname = cfg.irc.nick
        self.mps = cfg.mps
        self.twitter = twitter_api

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        log.info("connected")

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self, reason)
        log.info("disconnected")

    # callbacks for events

    def signedOn(self):
        """Called when bot has succesfully signed on to server."""
        log.info('signed on')
        self.join(self.factory.channel)

    def privmsg(self, user, channel, msg):
        """This will get called when the bot receives a message."""
        user = user.split('!', 1)[0]
        msg = msg.decode('utf-8')

        if user == 'rc-pmtpa':
            # TODO - check for channel ops instead
            log.debug(u"Incoming message: %r", msg)
            m = self.edit_re.match(msg)
            if m is not None:
                article = m.group(1)
                diffuri = m.group(2)
                author = m.group(3)
                log.debug(u"Noticed edit of %s by %s", article, author)
                if article in self.mps:
                    log.info(u"MP page %s edited by %s: %s", article, author, diffuri)
                    by_msg = 'anonymously'
                    if not self.ip_re.match(author):
                        by_msg = 'by %s' % author
                    # TODO shorten if >140 chars
                    self.twitter.PostUpdate(
                        u"%s Wikipedia article edited %s %s" % (
                            article, by_msg, diffuri))

    def alterCollidedNick(self, nickname):
        """Generate an altered version of a nickname that caused a collision
        to create an unused related name for subsequent registration."""
        return nickname + '_'


class EditsListenerFactory(protocol.ClientFactory):
    """A factory for EditsListeners.

    A new protocol instance will be created each time we connect to the server.
    """

    def __init__(self, cfg, twitter_api):
        self.channel = cfg.irc.channel
        self.cfg = cfg
        self.twitter = twitter_api

    def buildProtocol(self, addr):
        proto = EditsListener(self.cfg, self.twitter)
        proto.factory = self
        return proto

    def clientConnectionLost(self, connector, reason):
        """If we get disconnected, reconnect to server."""
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        print "connection failed:", reason
        reactor.stop()

def usage():
    return """%s - wikipedia IRC bot that tweets certain article changes.

Usage: %s [options] <config_file>

Options:
    -h, --help      Show this message and exit
""" % (sys.argv[0], sys.argv[0])

def main():
    """Main entry point for mps_edits"""
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], 'h', ['help'])
        for o, a in opts:
            if o in ('-h', '--help'):
                print usage()
                return 0
        if len(args) != 1:
            raise getopt.GetoptError('config file required.')
        config_filename = args[0]
    except getopt.GetoptError, e:
        print >> sys.stderr, e
        print >> sys.stderr, usage()
        return 2
    
    if not os.path.exists(config_filename):
        print >> sys.stderr, "E: Config file <%s> not found" % config_filename
        return 1

    # initialise config and logging
    try:
        cfg = config.Config(config_filename)
        twisted_log.startLogging(sys.stdout)
        logging.config.fileConfig(config_filename)
    except ConfigParser.NoSectionError, e:
        section = e.section
        print >> sys.stderr, "E: Missing [%s] section in config file" % section
        return 1

    log.debug('Starting up')

    # initialise Twitter API connection
    twitter_api = twitter.Api(
        consumer_key=cfg.twitter.consumer_key,
        consumer_secret=cfg.twitter.consumer_secret,
        access_token_key=cfg.twitter.access_token_key,
        access_token_secret=cfg.twitter.access_token_secret)
    user = twitter_api.VerifyCredentials()
    log.info("Logged into twitter: %s", user)

    # create factory protocol and application
    f = EditsListenerFactory(cfg, twitter_api)

    # connect factory to this host and port
    reactor.connectTCP(cfg.irc.server, cfg.irc.port, f)

    # run bot
    reactor.run()

if __name__ == '__main__':
    sys.exit(main())
