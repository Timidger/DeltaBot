def get_first_int(string):
    """ Returns the first integer in the string"""
    match = re.search('(\d+)', string)
    return int(match.group()) if match else 0


def flair_sorter(dic):
    """ Get numeric value from flair. """
    num = dic['flair_text']
    if num:
        return get_first_int(num)
    else:
        return 0


def skippable_line(line):
    """ Returns true if the given line is a quote or code """
    return re.search('(^    |^ *&gt;)', line) != None


def write_saved_id(filename, the_id):
    """ Write the previous comment's ID to file. """
    logging.debug("Saving ID %s to file %s" % (the_id, filename))
    with open(filename, 'w') as id_file:
        id_file.write(the_id if the_id else "None")
    #id_file = open(filename, 'w')
    #id_file.write(the_id if the_id else "None")
    #id_file.close()


def read_saved_id(filename):
    """ Get the last comment's ID from file. """
    logging.debug("Reading ID from file %s" % filename)
    try:
        #id_file = open(filename, 'r')
        with open(filename, 'r') as id_file:
            current = id_file.readline()
            if current == "None":
                current = None
        #id_file.close()
        return current
    except IOError:
        return None
