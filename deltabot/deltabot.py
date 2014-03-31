# encoding: utf-8


################################################################################
#                                                                              #
# Copyright 2013: Acebulf, alexames, PixelOrange, Snorrrlax, vaetrus, yaworsw  #
#                 and the moderators of http://www.reddit.com/r/changemyview   #
#                                                                              #
# This file is part of Deltabot sourcecode.                                    #
#                                                                              #
# Deltabot is free software: you can redistribute it and/or modify             #
# it under the terms of the GNU General Public License as published by         #
# the Free Software Foundation, either version 3 of the License, or            #
# (at your option) any later version.                                          #
#                                                                              #
# Deltabot is distributed in the hope that it will be useful,                  #
# but WITHOUT ANY WARRANTY; without even the implied warranty of               #
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the                #
# GNU General Public License for more details.                                 #
#                                                                              #
# You should have received a copy of the GNU General Public License            #
# along with Deltabot.  If not, see <http://www.gnu.org/licenses/>.            #
#                                                                              #
################################################################################
from __future__ import print_function

import re
import os
import sys
import time
import praw
import logging
import calendar
import datetime
import traceback
import collections
from random import choice


try:
    from HTMLParser import HTMLParser
except ImportError: # Python 3
    from html.parser import HTMLParser


logging.getLogger('requests').setLevel(logging.WARNING)


class DeltaBot(object):
    def __init__(self, config, test=False, test_reddit=None,
                test_recent=None):
        self.config = config
        self.reddit = reddit.Reddit(config, test, test_reddit, test_recent)
        self.messages = messages.Messages(config)
        if self.reddit.most_recent_comment_id:
            self.messages.scanned_comments.append(most_recent_comment_id)
        logging.info("Logged in as %s" % self.config.account['username'])

    # Wrapper function to keep side effects out of scan_comments
    def scan_comment_wrapper(self, comment, strict=True):
        parent = self.reddit.get_info(thing_id=comment.parent_id)

        log, message, awardee = self.messages.scan_comment(comment, parent,
                                                  self.messages.already_replied,
                                                  self.messages.is_parent_commenter_author,
                                                  self.messages.points_already_awarded_to_ancestor,
                                                  strict)
        logging.info(log)

        if message:
            comment.reply(message).distinguish()

        if awardee:
            self.reddit.award_points(awardee, comment)


    def command_add(self, message_body, strict):
        ids = re.findall(self.messages.comment_id_regex, message_body)
        for id in ids:
            comment = self.reddit.get_info(thing_id='t1_%s' % id)
            if type(comment) is praw.objects.Comment:
                self.messages.scan_comment_wrapper(comment, strict=strict)


    def scan_message(self, message):
        logging.info("Scanning message %s from %s" % (message.name,
                                                      message.author))
        if self.messages.is_moderator(message.author.name):
            command = message.subject.lower()
            if command == "force add":
                self.reddit.send_message("/r/" + self.config.subreddit,
                                         "Force Add Detected",
                                         "The Force Add command has been used "
                                         "on the following link(s):\n\n" + \
                                         message.body)
            if command == "add" or command == "force add":
                strict = (command != "force add")
                self.command_add(message.body, strict)
                self.reddit.send_message(message.author,
                                         "Add complete",
                                         "The add command has been "
                                         "completed on: " + message.body)

            elif command == "remove":
                # Todo
                pass

            elif command == "rescan":
                self.rescan_comments(message.body)

            elif command == "reset":
                self.messages.scanned_comments.clear()

            elif command == "stop":
                self.reddit.send_message("/r/" + self.config.subreddit,
                                         "Stop Message Confirmed",
                                         "NOTICE: The stop message has been "
                                         "issued and I have stopped running.")
                logging.warning("The stop command has been issued. If this was "
                                "not sent by you, please check as to why before"
                                " restarting.")
                message.mark_as_read()
                os._exit(1)


    def get_most_recent_comment(self):
        """Finds the most recently scanned comment,
        so we know where to begin the next scan"""
        most_recent_comment_id = None
        while self.messages.scanned_comments:
            comment = self.reddit.reddit.get_info(thing_id=self.scanned_comments[-1])
            if comment.body == '[deleted]':
                self.messages.scanned_comments.pop()
            else:
                most_recent_comment_id = self.messages.scanned_comments[-1]
                break

        return most_recent_comment_id


    def rescan_comment(self, bots_comment, orig_comment, awardees_comment):
        """Rescan comments that were too short"""
        awardee = awardees_comment.author.name

        if (self.messages.string_matches_message(bots_comment.body, 'too_little_text',
                                        awardee)
                and not self.messages.is_comment_too_short(orig_comment)
                and not self.messages.is_parent_commenter_author(orig_comment, awardees_comment)
                and not self.messages.points_already_awarded_to_ancestor(orig_comment, awardees_comment)):
            self.reddit.award_points(awardee, orig_comment)
            message = self.messages.get_message('confirmation') % (
                          awardee, self.config.subreddit, awardee
                          )
            bots_comment.edit(message).distinguish()

    # Keeps side effects out of rescan_comment to make testing easier
    def rescan_comment_wrapper(self, bots_comment):
        orig_comment = self.reddit.get_info(thing_id=bots_comment.parent_id)
        awardees_comment = self.reddit.get_info(thing_id=orig_comment.parent_id)

        self.rescan_comment(bots_comment, orig_comment, awardees_comment)

    def rescan_comments(self, message_body):
        ids = re.findall(self.messages.comment_id_regex, message_body)
        for id in ids:
            comment = self.reddit.get_info(thing_id='t1_%s' % id)
            if type(comment) is praw.objects.Comment:
                self.rescan_comment_wrapper(comment)


    def scan_comment_reply(self, comment):
        logging.info("Scanning comment reply from %s" % comment.author.name)

        bots_comment = self.reddit.get_info(thing_id=comment.parent_id)
        orig_comment = self.reddit.get_info(thing_id=bots_comment.parent_id)

        valid_commenter = (comment.author
                           and (comment.author == orig_comment.author
                                or self.messages.is_moderator(comment.author.name)))

        if valid_commenter:
            self.rescan_comment_wrapper(bots_comment)


    def scan_inbox(self):
        """ Scan a given list of messages for commands. If no list arg,
        then get newest comments from the inbox. """
        logging.info("Scanning inbox")

        messages = self.reddit.get_unread(unset_has_mail=True)

        for message in messages:
            if type(message) == praw.objects.Comment:
                self.messages.scan_comment_reply(message)
            elif type(message) == praw.objects.Message:
                self.scan_message(message)

            message.mark_as_read()


    def scan_mod_mail(self):
        pass


    def go(self):
        """ Start DeltaBot. """
        self.running = True
        reset_counter = 0
        while self.running:
            old_comment_id = self.messages.scanned_comments[-1] if self.messages.scanned_comments else None
            logging.info("Starting iteration at %s" % old_comment_id or "None")

            try:
                self.scan_inbox()
                self.scan_mod_mail()
                self.messages.scan_comments()
                if reddit.changes_made:
                    self.reddit.update_scoreboard()
            except:
                print ("Exception in user code:")
                print ('-'*60)
                traceback.print_exc(file=sys.stdout)
                print ('-'*60)

            if self.messages.scanned_comments and old_comment_id is not self.messages.scanned_comments[-1]:
                utils.write_saved_id(self.config.last_comment_filename,
                               self.messages.scanned_comments[-1])

            logging.info("Iteration complete at %s" % (self.messages.scanned_comments[-1] if
                                                       self.messages.scanned_comments else "None"))
            reset_counter = reset_counter + 1
            print ("Reset Counter at %s." % reset_counter)
            print ("When this reaches 10, the script will clear its history.")
            if reset_counter == 10:
              self.messages.scanned_comments.clear()
              reset_counter = 0
            logging.info("Sleeping for %s seconds" % self.config.sleep_time)
            time.sleep(self.config.sleep_time)
