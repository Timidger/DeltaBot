from itertools import izip, islice
import collections
from . import utils


def str_contains_token(text, tokens):
    """ Returns true if a given string contains one of the given tokens, as long
    as the token is not inside a quote or code block """
    lines = text.split('\n')
    in_quote = False
    for line in lines:
        if not line: # Empty string
            in_quote = False
        if in_quote:
            continue
        if not skippable_line(line):
            for token in tokens:
                if token in line:
                    return True
        else:
            in_quote = True
    return False

class Messages(object):
    def __init__(self, config):
        self.config = config
        self.scanned_comments = collections.deque([], 10)
        self.comment_id_regex = '(?:http://)?(?:www\.)?reddit\.com/r(?:eddit)?/' + \
                                self.config.subreddit + '/comments/[\d\w]+(?:/[^/]+)/?([\d\w]+)'
        longest = 0
        for token in self.config.tokens:
            if len(token) > longest:
                longest = len(token)
        self.minimum_comment_length = longest + \
                                      self.config.minimum_comment_length


    def get_message(self, message_key):
        """ Given a type of message select one of the messages from the
        configuration at random. """
        messages = self.config.messages[message_key]
        return choice(messages) + self.config.messages['append_to_all_messages']


    def string_matches_message(self, string, message_key, *args):
        messages = self.config.messages[message_key]
        for message in messages:
            appendation = self.config.messages['append_to_all_messages']
            full_message = (message % args) + appendation
            if string == full_message:
                return True
        return False


    # Functions with side effects are passed in as arguments
    # When testing, these can be replaced with mocks or "dummy functions"
    def scan_comment(self, comment, parent,
                     check_already_replied,
                     check_is_parent_commenter_author,
                     check_points_already_awarded_to_ancestor,
                     strict=True):
        logging.info("Scanning comment reddit.com/r/%s/comments/%s/c/%s by %s" %
                    (self.config.subreddit, comment.submission.id, comment.id,
                    comment.author.name if comment.author else "[deleted]"))

        # Logs describing the output will be returned so they can be used for testing
        log = ""
        message = None
        awardee = None

        if str_contains_token(comment.body, self.config.tokens) or not strict:
            parent_author = str(parent.author.name).lower()
            me = self.config.account['username'].lower()
            if parent_author == me:
                log = "No points awarded, replying to DeltaBot"

            elif check_already_replied(comment):
                log = "No points awarded, already replied"

            elif strict and check_is_parent_commenter_author(comment, parent):
                log = "No points awarded, parent is OP"
                message = self.get_message('broken_rule')

            elif strict and check_points_already_awarded_to_ancestor(comment, parent):
                log = "No points awarded, already awarded"
                message = self.get_message('already_awarded') % parent.author

            elif strict and self.messages.is_comment_too_short(comment):
                log = "No points awarded, too short"
                message = self.get_message('too_little_text') % parent.author

            else:
                awardee = parent.author.name
                message = self.get_message('confirmation') % (parent.author,
                    self.config.subreddit, parent.author)
        else:
            log = "No points awarded, comment does not contain Delta"

        return (log, message, awardee)


def scan_comments(self, fresh_comments):
        """ Scan a given list of comments for tokens. If a token is found,
        award points. """
        logging.info("Scanning new comments")

#        fresh_comments = self.subreddit.get_comments(params={'before': self.get_most_recent_comment()},
#                                                    limit=None)

        for comment in fresh_comments:
            self.scan_comment_wrapper(comment)
            if not self.scanned_comments or comment.name > self.scanned_comments[-1]:
                self.scanned_comments.append(comment.name)

    def already_replied(self, replies, test=False):
        """ Returns true if Deltabot has replied in replies

        Args:
            me(str): Name of the account being used (get from config)

            replies(list): List of the replies to a comment
        """
        message = self.get_message('confirmation')
        for reply in replies:
            author = str(reply.author).lower()
            me = self.config.account['username'].lower()
            if author == me:
                if str(message)[0:15] in str(reply):
                    return True
                else:
                    reply.delete()
                    return False
        return False

    def is_parent_commenter_author(self, comment, parent):
        """ Returns true if the author of the parent comment the submitter """
        comment_author = parent.author
        post_author = comment.submission.author
        return comment_author == post_author


    def points_awarded_to_children(self, awardee, comment, confirm_msg=None, me=None):
        """ Returns True if the OP awarded a delta to this comment or any of its
        children, by looking for confirmation messages from this bot. """

        if confirm_msg is None:
            confirm_msg = (self.get_message('confirmation')
                            % (awardee, self.config.subreddit, awardee))
        if me is None:
            me = self.config["account"]["username"]

        # If this is a confirmation message, return True now
        if comment.author == me and confirm_msg in comment.body:
            return True
        # Otherwise, recurse
        for reply in comment.replies:
            if self.points_awarded_to_children(awardee, reply, confirm_msg, me):
                return True
        return False


    def points_already_awarded_to_ancestor(self, comment, parent):
        awardee = parent.author
        # First, traverse to root comment
        root = parent
        while not root.is_root:
            root = self.reddit.get_info(thing_id=root.parent_id)
        # Then, delegate to the recursive function above
        return self.points_awarded_to_children(awardee, root)


    def messages.is_comment_too_short(self, comment):
        return len(comment.body) < self.minimum_comment_length


    def is_moderator(self, name):
        moderators = self.reddit.get_moderators(self.config.subreddit)
        mod_names = [mod.name for mod in moderators]
        return name in mod_names


