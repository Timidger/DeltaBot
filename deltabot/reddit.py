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


def markdown_to_scoreboard(text):
    scoreboard = {}
    for line in text.splitlines():
        if line[:2] == '##':
            tokens = line.split()
            username = tokens[1]
            score = int(tokens[2])
            current_user = scoreboard[username] = {"links": [], "score": score}
        elif line:
            current_user["links"].append(line[2:])
    return scoreboard


def scoreboard_to_markdown(scoreboard):
    text = ""
    try:
        itms = scoreboard.iteritems()
    except AttributeError: # Python 3
        itms = scoreboard.items()
    for key, value in itms:
        text += "## %s %s\n" % (key, value["score"])
        for link in value["links"]:
            text += "* %s\n" % link
        text += "\n"
    return text


class Reddit(object):
    def __init__(self, config, test=False, test_reddit=None,
                 test_recent=None):
        self.config = config
        if test:
            self.reddit = test_reddit
            self.most_recent_comment_id = test_recent
            self.reddit.login(*[self.config.test_account['username'],
                                self.config.test_account['password']])

        else:
            self.reddit = praw.Reddit(self.config.subreddit + ' bot',
                                      site_name=config.site_name)
            self.most_recent_comment_id = utils.read_saved_id(self.config.last_comment_filename)
            self.reddit.login(config.username, config.password)
        self.subreddit = self.reddit.get_subreddit(self.config.subreddit)
        self.changes_made = False # Ewwww


    def award_points(self, awardee, comment):
        """ Awards a point. """
        logging.info("Awarding point to %s" % awardee)
        self.adjust_point_flair(awardee)
        self.update_monthly_scoreboard(awardee, comment)
        self.update_wiki_tracker(comment)


    def send_first_time_message(self, recipient_name):
        first_time_message = self.config.private_message % (
                                 self.config.subreddit, recipient_name)
        self.reddit.send_message(recipient_name,
                                 "Congratulations on your first delta!",
                                 first_time_message)


    def adjust_point_flair(self, redditor, num_points=1):
        """ Recalculate a user's score and update flair. """
        self.changes_made = True

        flair = self.subreddit.get_flair(redditor)
        if flair['flair_text'] == None:
            points = 0
            css_class = ''
            self.send_first_time_message(redditor)
        elif flair:
            points = utils.get_first_int(flair['flair_text'])
            css_class = flair['flair_css_class']
        else:
            points = 0
            css_class = ''
            self.send_first_time_message(redditor)

        points += num_points
        if self.config.flair['css_class'] not in css_class:
            css_class += ' ' + self.config.flair['css_class']

        self.subreddit.set_flair(redditor,
                                 self.config.flair['point_text'] % points,
                                 css_class)


    def update_monthly_scoreboard(self, redditor, comment, num_points=1):
        logging.info("Updating monthly scoreboard")
        date = datetime.datetime.utcfromtimestamp(comment.created)
        scoreboard = self.get_this_months_scoreboard(date)
        page_title = "scoreboard_%s_%s" % (date.year, date.month)
        if redditor in scoreboard:
            entry = scoreboard[redditor]
        else:
            entry = scoreboard[redditor] = {"links": [], "score": 0}

        entry["links"].append("[%s](%s)" % (comment.submission.title,
                                            comment.permalink))
        entry["score"] += num_points

        self.reddit.edit_wiki_page(self.config.subreddit, page_title,
                                   scoreboard_to_markdown(scoreboard),
                                   "Updating monthly scoreboard")

    def get_this_months_scoreboard(self, date):
        page_title = "scoreboard_%s_%s" % (date.year, date.month)
        try:
            scoreboard_page = self.reddit.get_wiki_page(self.config.subreddit,
                                                        page_title)
            page_text = scoreboard_page.content_md
        except:
            page_text = ""
        return markdown_to_scoreboard(page_text)


    def get_top_ten_scores_this_month(self):
        """ Get a list of the top 10 scores this month """
        date = datetime.datetime.utcnow()
        scoreboard = self.get_this_months_scoreboard(date)
        score_list = []
        for user, value in scoreboard.iteritems():
            score_list.append({
                'user': user,
                'flair_text': self.config.flair['point_text'] % value['score']
            })
        score_list = sorted(score_list, key=utils.flair_sorter)
        score_list.reverse()
        while len(score_list) < 10:
            score_list.append({'user': 'none', 'flair_text': 'no score'})
        return score_list[0:10]


    def update_scoreboard(self):
        """ Update the top 10 list with highest scores. """
        logging.info("Updating scoreboard")
        now = datetime.datetime.utcnow()
        top_scores = self.get_top_ten_scores_this_month()
        score_table = [
            "\n\n# Top Ten Viewchangers (%s)" % calendar.month_name[now.month],
            self.config.scoreboard['table_head'],
            self.config.scoreboard['table_leader_entry'] % (
                top_scores[0]['user'], top_scores[0]['flair_text'],
                self.config.subreddit, top_scores[0]['user']
            )
        ]

        for i in range(1, 10):
            table_entry = self.config.scoreboard['table_entry'] % (
                i+1, top_scores[i]['user'], top_scores[i]['flair_text'],
                self.config.subreddit, top_scores[i]['user']
                )
            score_table.append(table_entry)

        settings = self.subreddit.get_settings()
        old_desc = settings['description']
        # IMPORTANT: this splits the description on the _____ token.
        # Don't use said token for anything other than dividing sections
        # or else this breaks.
        split_desc = old_desc.split("_____")
        split_desc[len(split_desc)-1] = "".join(score_table)
        new_desc = ""
        for section in split_desc:
            if section != split_desc[0]:
                new_desc = new_desc + "_____" + section.replace("&amp;", "&")
        self.subreddit.update_settings(description=new_desc)
        self.changes_made = False



    def get_top_ten_scores(self):
        """ Get a list of the top 10 scores. """
        flair_list = [f for f in self.subreddit.get_flair_list(limit=None)]
        flair_list = sorted(flair_list, key=utils.flair_sorter)
        flair_list.reverse()
        while len(flair_list) < 10:
            flair_list.append({'user': 'none', 'flair_text': 'no score'})
        return flair_list[0:10]


    def update_wiki_tracker(self, comment):
        logging.info("Updating wiki")
        """ Update wiki page of person earning the delta

            Note: comment passed in is the comment awarding the delta,
            parent comment is the one earning the delta
        """
        comment_url = comment.permalink
        submission_url = comment.submission.permalink
        submission_title = comment.submission.title
        parent = self.reddit.get_info(thing_id=comment.parent_id)
        parent_author = parent.author.name
        author_flair = str(self.subreddit.get_flair(parent_author))
        author_flair = re.search("(flair_text': u')(\d*)", author_flair)
        flair_count = "0 deltas"
        if author_flair:
            flair_count = author_flair.group(2)
            if flair_count == "1":
                flair_count = "1 delta"
            else:
                flair_count = flair_count + " deltas"
        awarder_name = comment.author.name
        today = datetime.date.today()

        # try to get wiki page for user, throws exception if page doesn't exist
        try:
            user_wiki_page = self.reddit.get_wiki_page(self.config.subreddit,
                                                       "user/" + parent_author)

            # get old wiki page content as markdown string, and unescaped any
            # previously escaped HTML characters
            old_content = HTMLParser().unescape(user_wiki_page.content_md)

            # Alter how many deltas is in the first line
            try:
                old_content = re.sub("([0-9]+) delta[s]?", flair_count,
                                     old_content)
            except:
                print ("The 'has received' line in the wiki has failed to update.")
            # compile regex to search for current link formatting
            # only matches links that are correctly formatted, so will not be
            # broken by malformed or links made by previous versions of DeltaBot
            regex = re.compile("\\* \\[%s\\]\\(%s\\) \\(\d+\\)" % (
                re.escape(submission_title), re.escape(submission_url)
                ))
            # search old page content for link
            old_link = regex.search(old_content)

            # variable for updated wiki content
            new_content = ""

            # old link exists, only increase number of deltas for post
            if old_link:
                # use re.sub to increment number of deltas in link
                new_link = re.sub(
                    "\((\d+)\)",
                    lambda match: "(" + str(int(match.group(1)) + 1) + ")",
                                  old_link.group(0)
                    )

                # insert link to new delta
                new_link += "\n    1. [Awarded by /u/%s](%s) on %s/%s/%s" % (
                    awarder_name, comment_url + "?context=2",
                    today.month, today.day, today.year
                    )

                #use re.sub to replace old link with new link
                new_content = re.sub(regex, new_link, old_content)

            # no old link, create old link with initial count of 1
            else:
                # create link and format as markdown list item
                # "?context=2" means link shows comment earning the delta and
                # the comment awarding it
                # "(1)" is the number of deltas earned from that comment
                # (1 because this is the first delta the user has earned)
                add_link = "\n\n* [%s](%s) (1)\n    1. [Awarded by /u/%s](%s) on %s/%s/%s" % (submission_title,
              submission_url,
              awarder_name,
              comment_url + "?context=2",
              today.month,
              today.day,
              today.year)

                # get previous content as markdown string and append new content
                new_content = user_wiki_page.content_md + add_link

            # overwrite old content with new content
            self.reddit.edit_wiki_page(self.config.subreddit,
                                       user_wiki_page.page,
                                       new_content,
                                       "Updated delta links.")

        # if page doesn't exist, create page with initial content
        except:

            # create header for new wiki page
            initial_text = "/u/%s has received 1 delta for the following comments:" % parent_author

            # create link and format as markdown list item
            # "?context=2" means link shows comment earning the delta and the comment awarding it
            # "(1)" is the number of deltas earned from that comment
            # (1 because this is the first delta the user has earned)
            add_link = "\n\n* [%s](%s) (1)\n    1. [Awarded by /u/%s](%s) on %s/%s/%s" % (submission_title,
          submission_url,
          awarder_name,
          comment_url + "?context=2",
          today.month, today.day, today.year)

            # combine header and link
            full_update = initial_text + add_link

            # write new content to wiki page
            self.reddit.edit_wiki_page(self.config.subreddit,
                                       "user/" + parent_author,
                                       full_update,
                                       "Created user's delta links page.")

            """Add new awardee to Delta Tracker wiki page"""

            # get delta tracker wiki page
            delta_tracker_page = self.reddit.get_wiki_page(
                                                          self.config.subreddit,
                                                          "delta_tracker")

            # retrieve delta tracker page content as markdown string
            delta_tracker_page_body = delta_tracker_page.content_md

            # create link to user's wiki page as markdown list item
            new_link = "\n\n* /u/%s -- [Delta List](/r/%s/wiki/%s)" % (
                                                          parent_author,
                                                          self.config.subreddit,
                                                          parent_author)

            # append new link to old content
            new_content = delta_tracker_page_body + new_link

            # overwrite old page content with new page content
            self.reddit.edit_wiki_page(self.config.subreddit,
                                       "delta_tracker",
                                       new_content,
                                       "Updated tracker page.")

