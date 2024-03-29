import secrets
import psycopg2
from datetime import datetime

def initiateArticleTable(connection):
    articleTableContentList = [
            "id BIGSERIAL NOT NULL PRIMARY KEY",
            "title VARCHAR(150) NOT NULL",
            "description VARCHAR(350)",
            "url VARCHAR(300) NOT NULL",
            "image_url VARCHAR(300)",
            "author VARCHAR(100) DEFAULT NULL",
            "publish_date TIMESTAMP WITH TIME ZONE DEFAULT NULL",
            "profile VARCHAR(30) NOT NULL",
            "scraped BOOL NOT NULL",
            "inserted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP",
            "file_path VARCHAR(150) DEFAULT NULL"
            ]

    return createTable(connection, "articles", articleTableContentList)

def initiateUserTable(connection):
    userTableContentList = [
        "username VARCHAR(64) NOT NULL PRIMARY KEY",
        "selected_article_ids BIGINT[]",
        "password_hash VARCHAR(100) NOT NULL",
        "id VARCHAR(128) NOT NULL"
    ]
    return createTable(connection, "osinter_users", userTableContentList)


def initiateAdmin(connection):

    adminUsername = "osinter_admin"
    adminPassword = secrets.token_urlsafe(30)

    # Creating the new admin user
    createUser(connection, adminUsername, adminPassword)

    with connection.cursor() as cur:
        cur.execute("ALTER USER {} WITH SUPERUSER;".format(adminUsername))
    connection.commit()

    # Will be used for initiating new connection using new superuser
    dbName = connection.info.dbname

    # Make sure to close the old connection
    connection.close()

    # Switching the connection from the prior superuser to the newly created one
    connection = psycopg2.connect("dbname={} user={} password={}".format(dbName, adminUsername, adminPassword))

    return adminPassword, connection

def initiateUsers(connection):

    # It's important the the reader user is created first, since the other roles inherit from it.
    # IMPORTANT! All names should include lowercase letters ONLY
    # The passwordStoragePerms is used to mark the unix permissions of the file that will be storing the passwords on disk when deploying the program.
    users = [
                {
                    "privs" : [["articles", "SELECT"], ["articles_id_seq", "SELECT"], ["osinter_users", "SELECT(selected_article_ids, username)"]],
                    "username" : "reader",
                    "passwordStoragePerms": 0o440,
                    "inherit" : False
                },
                {
                    "privs" : [["osinter_users", "SELECT", "INSERT"]],
                    "username": "user_creator",
                    "passwordStoragePerms": 0o440,
                    "inherit" : "reader"
                },
                {
                    "privs" : [["osinter_users", "SELECT"]],
                    "username": "auth",
                    "passwordStoragePerms": 0o440,
                    "inherit" : "reader"
                },
                {
                    "privs" : [["osinter_users", "UPDATE(selected_article_ids)"]],
                    "username": "article_marker",
                    "passwordStoragePerms": 0o440,
                    "inherit" : "reader"
                },
                {
                    "privs" : [["articles", "SELECT", "UPDATE", "INSERT"], ["articles_id_seq", "UPDATE", "SELECT"]],
                    "username" : "writer",
                    "passwordStoragePerms": 0o400,
                    "inherit" : "reader"
                }
            ]

    usernamePasswordAndPerms = { user['username'] : { "password" : secrets.token_urlsafe(30), "perms" : user["passwordStoragePerms"] } for user in users }

    for user in users:
        createUser(connection, user['username'], usernamePasswordAndPerms[user['username']]["password"])

        grantUserPrivs(connection, user["username"], user["inherit"], user['privs'])

    return usernamePasswordAndPerms


# Function for creating new users with certain priviledges
def createUser(connection, username, userPassword=""):
    connectedUser = connection.info.user
    with connection.cursor() as cur:
        # Checking whether the user already exists
        cur.execute("SELECT * FROM pg_roles WHERE rolname=%s;", (username,))
        # In case the user already exist we have to reassign the objects owned by them, before deleting them, the latter which is done to make sure they have the right priviledges
        if cur.fetchall() != []:
            cur.execute("REASSIGN OWNED BY {} TO {};".format(username, connectedUser))
            cur.execute("DROP OWNED BY {};".format(username))
            cur.execute("DROP USER {};".format(username))

        if userPassword == "":
            cur.execute("CREATE USER {};".format(username))
        else:
            cur.execute("CREATE USER {} WITH ENCRYPTED PASSWORD %s;".format(username), (userPassword,))

    connection.commit()

def grantUserPrivs(connection, username, inherit, privLists):
    with connection.cursor() as cur:
        if inherit:
            cur.execute("GRANT {} TO {}".format(inherit, username))
        for privList in privLists:
            tableName = privList.pop(0)
            cur.execute("GRANT {} ON {} TO {};".format(", ".join(privList), tableName, username))

    connection.commit()

# Function for creating new tables
def createTable(connection, tableName, tableContentList):
    # Making sure the tablename is in all lowercase
    tableName = tableName.lower()
    # Opening new cursor that will automatically close when function is done
    with connection.cursor() as cur:
        # Checking if a table with the specified wanted name already exists
        cur.execute("SELECT to_regclass('public.{}');".format(tableName))
        if cur.fetchall()[0][0] == None:
            # Creating the text used to specify the contents of the table
            tableContents = ", ".join([x for x in tableContentList])
            # Creating the table with the specified content
            cur.execute("CREATE TABLE {} ({});".format(tableName, tableContents))
            # Writing the changes to the database
            connection.commit()
            # Will return true if table has been created or false if table already existed
            return True
        else:
            return False

# Will mark an article as of interrest or remove an article as of interrest for the [osinter_user] based on whether mark is true or false. articleTableName is the name of the table storing the articles (used for verifying that there exists a table with that name) and userTableName is the name of the table holding the user and their preferences
def markArticle(connection, articleTableName, userTableName, osinter_user, articleID, mark):
    with connection.cursor() as cur:
        # Verifying that the user exists
        cur.execute("SELECT EXISTS(SELECT 1 FROM {} WHERE username = %s);".format(userTableName), (osinter_user,))
        if cur.fetchall() == []:
            return "User does not seem to exist"
        else:
            # Verifying that the article exists
            cur.execute("SELECT EXISTS(SELECT 1 FROM {} WHERE id = %s);".format(articleTableName), (articleID,))
            if cur.fetchall() == []:
                return "Article does not seem to exist"
            else:
                if mark:
                    # The article ID has to be formated as an array if inserting in the DB, since the insertion combines the existing array, with the new ID to append it.
                    articleIDArray = "{" + str(articleID) + "}"
                    # Combines the array from the DB with the new ID, and takes all the uniqe entries from that so that duplicates are avoided
                    cur.execute("UPDATE {0} SET selected_article_ids = (SELECT ARRAY(SELECT DISTINCT UNNEST(selected_article_ids || %s)) FROM {0} WHERE username = %s) WHERE username = %s;".format(userTableName), (articleIDArray, osinter_user, osinter_user))
                else:
                    cur.execute("UPDATE {} SET selected_article_ids = array_remove(selected_article_ids, %s::bigint) WHERE username = %s;".format(userTableName), (articleID, osinter_user))

    connection.commit()
    return True

# Function for checking looping through a list (IDList) containing ID's of articles, and checking if they have been marked as interresting by [username]. Will return list consisting of true or false (true if it has been marked, false if not), each corresponding to the ID at that index in the IDList
def checkIfArticleMarked(connection, userTableName, IDList, username):
    with connection.cursor() as cur:

        cur.execute("SELECT selected_article_ids FROM {} WHERE username = %s".format(userTableName), (username,))

        DBResults = cur.fetchall()

        markedArticles = DBResults[0][0]

        if markedArticles == None:
            return [False] * len(IDList)

        # The final list that will be returned that will consist of true and false.
        IDMarkings = [ ID in markedArticles for ID in IDList ]

        return IDMarkings

# Function for writting OG tags to database
def writeOGTagsToDB(connection, OGTags, tableName):
    # Making sure the tablename is in all lowercase
    tableName = tableName.lower()
    # List to hold all the urls along with the profile names off the articles that haven't been scraped and saved in the database before so the whole article can be scraped
    newUrls = list()
    with connection.cursor() as cur:
        for newsSite in OGTags:
            # Looping through each collection of tags an creating a list inside the original list to hold articles from each news site
            newUrls.append([newsSite])
            for tags in OGTags[newsSite]:
                # Checking if the article is already stored in the database using the URL as that is probably not going to change and is uniqe
                cur.execute("SELECT exists (SELECT 1 FROM {} WHERE url = %s);".format(tableName), (tags['url'],))
                if cur.fetchall()[0][0] == False:
                    # Adding the url to list of new articles since it was not found in the database
                    newUrls[-1].append(tags['url'])
                    insertQuery = "INSERT INTO {} (title, description, url, image_url, author, publish_date, profile, scraped, inserted_at) VALUES (%s, %s, %s, %s, %s, %s, %s, false, NOW());".format(tableName)
                    insertParameters = (tags['title'][:150], tags['description'][:350], tags['url'], tags['image'], tags['author'], tags['publishDate'] if tags['publishDate'] != None else datetime.now(), newsSite)
                    cur.execute(insertQuery, insertParameters)
    connection.commit()
    # Return the list of urls not already in the database so they can be scraped
    return newUrls

def requestOGTagsFromDB(connection, tableName, profileList, limit, idList=[]):

    # Making sure the limit given is actually an intenger
    if type(limit) != int:
        raise Exception("An internal number given when trying to access the database appears to not be a number but instead: \"{}\"".format(limit))

    # The dictionary to hold the OG tags
    OGTagCollection = []

    with connection.cursor() as cur:

        # Which collumns to extract data from
        collumns = "id, title, description, url, image_url, author, publish_date, profile"

        # Take the [limit] newest articles from a specfic source that has been scraped
        if idList != []:
            cur.execute("SELECT {} FROM {} WHERE scraped=true AND id=ANY(%s) AND profile=ANY(%s) ORDER BY publish_date DESC;".format(collumns, tableName), (idList, profileList))
        else:
            cur.execute("SELECT {} FROM {} WHERE scraped=true AND profile=ANY(%s) ORDER BY publish_date DESC LIMIT {};".format(collumns, tableName, limit), (profileList,))
        queryResults = cur.fetchall()

        # Adding them to the final OG tag collection
        for result in queryResults:
            OGTagCollection.append({descriptor:value for (descriptor,value) in zip(collumns.split(", "), result)})
    return OGTagCollection

def findUnscrapedArticles(connection, tableName, profileList):
    articleCollection = []

    with connection.cursor() as cur:
        # Go through each of the profiles one by one, so that the urls will be grouped by profile making scraping easier
        for profile in profileList:
            # Create a new list inside the "master" list with the first entry being the profile
            articleCollection.append([profile])
            # Finding all articles for that specific profile that hasn't yet been marked as scraped
            cur.execute("SELECT * FROM {} WHERE profile=%s AND scraped=false".format(tableName), (profile,))
            queryResults = cur.fetchall()

            # Adding the results one by one to the latest added list in the "master" list which is the one for the current profile
            for result in queryResults:
                # Only adding the url as that is the only needed part
                articleCollection[-1].append(result[3])

    return articleCollection

# Function for taking in a list of lists of articles with the first entry of each list being the name of the profile, and then removing all the articles that already has been saved in the database
def filterArticleURLList(connection, tableName, articleURLCollection):
    # The final list that will be returned in the same format as the articleURLCollection list, but with the already stored articles removed
    filteredArticleURLList = []

    with connection.cursor() as cur:
        for URLList in articleURLCollection:
            # The first element is always just the profile, so that should simply be copied to the filtered list
            filteredArticleURLList.append([URLList.pop(0)])
            for URL in URLList:
                # Checking if the article is already stored in the database using the URL as that is probably not going to change and is uniqe
                cur.execute("SELECT exists (SELECT 1 FROM {} WHERE url = %s);".format(tableName), (URL,))
                if cur.fetchall()[0][0] == False:
                    filteredArticleURLList[-1].append(URL)

    return filteredArticleURLList


def requestProfileListFromDB(connection, tableName):
    with connection.cursor() as cur:
        # Get the different profiles stored in the database
        cur.execute("SELECT DISTINCT profile FROM {};".format(tableName))
        profiles = [item for element in cur.fetchall() for item in element]
        return profiles

# Currently, the articles are inserted in the DB as OGTags and then the full article is scraped. To make sure that one does not end up with articles that are in the DB but not scraped in full, the articles will be marked as scraped in the DB using this function when they have actually been scraped
def markAsScraped(connection, URL, filePath, tableName):
    with connection.cursor() as cur:
        # The full filepath of the file (which is [profile]/[filename] will also be noted, so it's easier to find when the front ends needs to render the MD files
        cur.execute("UPDATE {} SET scraped = true, file_path = %s WHERE url = %s;".format(tableName), (filePath, URL))
        connection.commit()

# Simply find the filepath of a given article with articleId. Used by front end when rendering MD files
def returnArticleFilePathById(connection, articleId, tableName):
    # Making sure the id given is actually an intenger
    if type(articleId) != int:
        raise Exception("An internal number given when trying to access the database appears to not be a number but instead: \"{}\"".format(articleId))

    with connection.cursor() as cur:
        cur.execute("SELECT file_path FROM {} WHERE id = %s".format(tableName), (articleId,))
        results = cur.fetchall()

        if results == []:
            return ""
        else:
            return results[0][0]
