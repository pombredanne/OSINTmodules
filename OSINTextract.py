# For parsing html
from bs4 import BeautifulSoup

# For parsing application/ld+json
import json

import re


# Used for matching the relevant information from LD+JSON
JSONPatterns = {
        "publishDate":  re.compile(r'("datePublished": ")(.*?)(?=")'),
        "author":       re.compile(r'("@type": "Person",.*?"name": ")(.*?)(?=")')
        }

# Function for using the class of a container along with the element type and class of desired html tag (stored in the contentDetails variable) to extract that specific tag. Data is found under the "scraping" class in the profiles.
def locateContent(contentDetails, soup, multiple=False, recursive=True):

    # Getting the html tag that surrounds that tag we are interrested in, but only look for it if the class is actually given (otherwise this will only return HTML tags completly without a class)
    if contentDetails['containerClass'] != "":
        contentContainer = soup.find(class_=contentDetails['containerClass'])
    else:
        contentContainer = soup

    try:

        # The same case with not looking for the class if it's empty
        if contentDetails['class'] == "":
            # We only want the first entry for some things like date and author, but for the text, which is often split up into different <p> tags we want to return all of them
            if multiple:
                return contentContainer.find_all(contentDetails['element'].split(';'), recursive=recursive)
            else:
                return contentContainer.find(contentDetails['element'], recursive=recursive)
        else:
            if multiple:
                return contentContainer.find_all(contentDetails['element'].split(';'), class_=contentDetails['class'], recursive=recursive)
            else:
                return contentContainer.find(contentDetails['element'], class_=contentDetails['class'], recursive=recursive)

    except:
        return BeautifulSoup("Unknown", "html.parser")

# Function used for removing certain tags with or without class from a soup. Takes in a list of element tag and class in the format: "tag,class;tag,class;..."
def cleanSoup(soup, HTMLTagsAndClasses):
    for TagAndClass in HTMLTagsAndClasses.split(";"):
        for tag in soup.find_all(TagAndClass.split(",")[0], class_=TagAndClass.split(",")[1]):
            tag.decompose()

    return soup


# Function for collecting all the small details from the article (title, subtitle, date and author)
def extractArticleDetails(contentDetails, soup):
    details = list()
    for detail in contentDetails:
        if contentDetails[detail] != "":
            details.append(locateContent(contentDetails[detail], soup).get_text())
        else:
            details.append("Unknown")

    return details

def extractArticleContent(textDetails, soup, clearText=False, delimiter='\n'):

    # Clean the textlist for unwanted html elements
    if textDetails['remove'] != "":
        cleanedSoup = cleanSoup(soup, textDetails['remove'])
        textList = locateContent(textDetails, cleanedSoup, True, (textDetails['recursive'] == 'True'))
    else:
        textList = locateContent(textDetails, soup, True, (textDetails['recursive'] == 'True'))

    # Get a title image too, if specified in the profile
    if textDetails['headerImage'] != "":
        # Extracting the title image
        headerImage = locateContent(textDetails['headerImage'], soup)
        # Inserting it in the existing soup containing the text and other wanted elements, as the first element, if it was possible to extract one
        if headerImage != None:
            textList.insert(0, headerImage)

    if textList == "Unknown":
        raise Exception("Wasn't able to fetch the text for the following soup:" + str(soup))

    assembledText = ""

    # Loop through all the <p> tags, extract the text and add them to string with newline in between
    for element in textList:
        if clearText:
            assembledText = assembledText + element.get_text() + delimiter
        else:
            assembledText = assembledText + str(element) + delimiter

    return assembledText

# Function for scraping everything of relevans in an article
def extractAllDetails(currentProfile, articleSource):

    # Parsing full source code for the article to a soup
    articleSoup = BeautifulSoup(articleSource, 'html.parser')

    articleDetails =    extractArticleDetails(currentProfile['scraping']['details'], articleSoup)
    articleContent =    extractArticleContent(currentProfile['scraping']['content'], articleSoup)
    articleClearText =  extractArticleContent(currentProfile['scraping']['content'], articleSoup, True)

    return articleDetails, articleContent, articleClearText

# Function for scraping meta information (like title, author and publish date) from articles. This both utilizes the OG tags and LD+JSON data, and while the proccess for extracting the OG tags is fairly simply as those is (nearly) always following the same standard, the LD+JSON data is a little more complicated. Here the data isn't parsed as JSON, but rather as a string where the relevant pieces of information is extracted using regex. It's probably ugly and definitly not the officially "right" way of doing this, but different placement of the information in the JSON object on different websites using different attributes made parsing the information from a python JSON object near impossible. As such, be warned that this function is not for the faint of heart
def extractMetaInformation(pageSoup):
    OGTags = {'author' : None, 'publishDate': None}

    # Extract the 3 relevant og tags from the website
    for tag in ["og:title", "og:description", "og:image"]:
        try:
            OGTags[tag] = (pageSoup.find("meta", property=tag).get('content'))
        except:
            OGTags[tag] = None

    # Use ld+json to extract extra information not found in the meta OG tags like author and publish date
    JSONScriptTags = pageSoup.find_all("script", {"type":"application/ld+json"})

    for scriptTag in JSONScriptTags:
        # Converting to and from JSON to standardize the format to avoid things like line breaks and excesive spaces at the end and start of line. Will also make sure there spaces in the right places between the keys and values so it isn't like "key" :"value" and "key  : "value" but rather "key": "value" and "key": "value".
        scriptTagString = json.dumps(json.loads("".join(scriptTag.contents)))
        for pattern in JSONPatterns:
            articleDetailPatternMatch = JSONPatterns[pattern].search(scriptTagString)
            if articleDetailPatternMatch != None:
                # Selecting the second group, since the first one is used to located the relevant information. The reason for not using lookaheads is because python doesn't allow non-fixed lengths of those, which is needed when trying to select pieces of text that doesn't always conform to a standard.
                OGTags[pattern] = articleDetailPatternMatch.group(2)

    return OGTags
