from slack_sdk import WebClient
import json
import argparse
import os
import io
import shutil
import copy
from datetime import datetime, timezone
from pick import pick
from time import sleep
from urllib.parse import urlparse
import requests

# fetches the complete message history for a channel/group/im
#
# pageableObject could be:
# slack.channel
# slack.groups
# slack.im
#
# channelId is the id of the channel/group/im you want to download history for.

# Create wrapper classes for using slack_sdk in place of slacker
class Slacker_Wrapper:
    def __init__(self, token):
        self.client = WebClient(token=token)
        self.channels = self.Convo(self.client, "public_channel")
        self.groups = self.Convo(self.client, "private_channel,mpim")
        self.im = self.Convo(self.client, "im")
        self.auth = self.Auth(self.client)
        self.users = self.Users(self.client)
    
    class Auth:
        def __init__ (self, webclient):
            self.client = webclient
        
        def test(self):
            return self.client.auth_test()
    
    class Convo:
        def __init__ (self, webclient, types):
            self.client = webclient
            self.types = types

        def history(self, channel, latest, oldest, count):
            return self.client.conversations_history(channel=channel, latest=latest, oldest=oldest, count=count)
        
        def list(self):
            return self.client.conversations_list(types=self.types)
    
    class Users:
        def __init__(self, webclient):
            self.client = webclient
        
        def list(self):
            return self.client.users_list()
    
    class Channels:
        def __init__(self, webclient):
            self.client = webclient
        
        def list(self):
            return self.client.users_list()


def getHistory(pageableObject, channelId, pageSize = 100):
    messages = []
    lastTimestamp = None

    while(True):
        sleep(1) # Respect the Slack API rate limit
        response = pageableObject.history(
            channel = channelId,
            latest    = lastTimestamp,
            oldest    = 0,
            count     = pageSize
        ).data

        messages.extend(response['messages'])

        if (response['has_more'] == True):
            lastTimestamp = messages[-1]['ts'] # -1 means last element in a list
        else:
            break

    messages.sort(key = lambda message: message['ts'])

    return messages


def mkdir(directory):
    if not os.path.isdir(directory):
        os.makedirs(directory)


# create datetime object from slack timestamp ('ts') string
def parseTimeStamp( timeStamp ):
    if '.' in timeStamp:
        t_list = timeStamp.split('.')
        if len( t_list ) != 2:
            raise ValueError( 'Invalid time stamp' )
        else:
            return datetime.fromtimestamp( float(t_list[0]), timezone.utc )


# move channel files from old directory to one with new channel name
def channelRename( oldRoomName, newRoomName ):
    # check if any files need to be moved
    if not os.path.isdir( oldRoomName ):
        return
    mkdir( newRoomName )
    for fileName in os.listdir( oldRoomName ):
        shutil.move( os.path.join( oldRoomName, fileName ), newRoomName )
    os.rmdir( oldRoomName )


def writeMessageFile( fileName, messages ):
    directory = os.path.dirname(fileName)

    # if there's no data to write to the file, return
    if not messages:
        return

    if not os.path.isdir( directory ):
        mkdir( directory )

    with open(fileName, 'w') as outFile:
        json.dump( messages, outFile, indent=4)


# parse messages by date
def parseMessages( roomDir, messages, roomType ):
    nameChangeFlag = roomType + "_name"

    currentFileDate = ''
    currentMessages = []
    for message in messages:
        #first store the date of the next message
        ts = parseTimeStamp( message['ts'] )
        fileDate = '{:%Y-%m-%d}'.format(ts)

        #if it's on a different day, write out the previous day's messages
        if fileDate != currentFileDate:
            outFileName = u'{room}/{file}.json'.format( room = roomDir, file = currentFileDate )
            writeMessageFile( outFileName, currentMessages )
            currentFileDate = fileDate
            currentMessages = []

        # check if current message is a name change
        # dms won't have name change events
        if roomType != "im" and ( 'subtype' in message ) and message['subtype'] == nameChangeFlag:
            roomDir = message['name']
            oldRoomPath = message['old_name']
            newRoomPath = roomDir
            channelRename( oldRoomPath, newRoomPath )

        currentMessages.append( message )
    outFileName = u'{room}/{file}.json'.format( room = roomDir, file = currentFileDate )
    writeMessageFile( outFileName, currentMessages )

def filterConversationsByName(channelsOrGroups, channelOrGroupNames):
    return [conversation for conversation in channelsOrGroups if conversation['name'] in channelOrGroupNames]

def promptForPublicChannels(channels):
    channelNames = [channel['name'] for channel in channels]
    selectedChannels = pick(channelNames, 'Select the Public Channels you want to export:', multi_select=True)
    return [channels[index] for channelName, index in selectedChannels]

# fetch and write history for all public channels
def fetchPublicChannels(channels):
    print("Fetching", len(channels), "public channels")
    if dryRun:
        print("Public Channels selected for export:")
        for channel in channels:
            print(channel['name'])
        print()
        return

    for channel in channels:
        channelDir = channel['name']
        print("Fetching history for Public Channel: {0}".format(channelDir))
        mkdir( channelDir )
        messages = getHistory(slack.channels, channel['id'])
        parseMessages( channelDir, messages, 'channel')

# write channels.json file
def dumpChannelFile():
    print("Making channels file")

    private = []
    mpim = []

    for group in groups:
        if group['is_mpim']:
            mpim.append(group)
            continue
        private.append(group)
    
    # slack viewer wants DMs to have a members list, not sure why but doing as they expect
    for dm in dms:
        dm['members'] = [dm['user'], tokenOwnerId]

    #We will be overwriting this file on each run.
    with open('channels.json', 'w') as outFile:
        json.dump( channels , outFile, indent=4)
    with open('groups.json', 'w') as outFile:
        json.dump( private , outFile, indent=4)
    with open('mpims.json', 'w') as outFile:
        json.dump( mpim , outFile, indent=4)
    with open('dms.json', 'w') as outFile:
        json.dump( dms , outFile, indent=4)

def filterDirectMessagesByUserNameOrId(dms, userNamesOrIds):
    userIds = [userIdsByName.get(userNameOrId, userNameOrId) for userNameOrId in userNamesOrIds]
    return [dm for dm in dms if dm['user'] in userIds]

def promptForDirectMessages(dms):
    dmNames = [userNamesById.get(dm['user'], dm['user'] + " (name unknown)") for dm in dms]
    selectedDms = pick(dmNames, 'Select the 1:1 DMs you want to export:', multi_select=True)
    return [dms[index] for dmName, index in selectedDms]

# fetch and write history for all direct message conversations
# also known as IMs in the slack API.
def fetchDirectMessages(dms):
    print("Fetching", len(dms), "1:1 DMs")
    if dryRun:
        print("1:1 DMs selected for export:")
        for dm in dms:
            print(userNamesById.get(dm['user'], dm['user'] + " (name unknown)"))
        print()
        return

    for dm in dms:
        name = userNamesById.get(dm['user'], dm['user'] + " (name unknown)")
        print("Fetching 1:1 DMs with {0}".format(name))
        dmId = dm['id']
        mkdir(dmId)
        messages = getHistory(slack.im, dm['id'])
        parseMessages( dmId, messages, "im" )

def promptForGroups(groups):
    groupNames = [group['name'] for group in groups]
    selectedGroups = pick(groupNames, 'Select the Private Channels and Group DMs you want to export:', multi_select=True)
    return [groups[index] for groupName, index in selectedGroups]

# fetch and write history for specific private channel
# also known as groups in the slack API.
def fetchGroups(groups):
    print("Fetching", len(groups), "Private Channels and Group DMs")
    if dryRun:
        print("Private Channels and Group DMs selected for export:")
        for group in groups:
            print(group['name'])
        print()
        return

    for group in groups:
        groupDir = group['name']
        mkdir(groupDir)
        messages = []
        print("Fetching history for Private Channel / Group DM: {0}".format(group['name']))
        messages = getHistory(slack.groups, group['id'])
        parseMessages( groupDir, messages, 'group' )

# fetch all users for the channel and return a map userId -> userName
def getUserMap():
    global userNamesById, userIdsByName
    for user in users:
        userNamesById[user['id']] = user['name']
        userIdsByName[user['name']] = user['id']

# stores json of user info
def dumpUserFile():
    #write to user file, any existing file needs to be overwritten.
    with open( "users.json", 'w') as userFile:
        json.dump( users, userFile, indent=4 )

# get basic info about the slack channel to ensure the authentication token works
def doTestAuth():
    testAuth = slack.auth.test().data
    teamName = testAuth['team']
    currentUser = testAuth['user']
    print("Successfully authenticated for team {0} and user {1} ".format(teamName, currentUser))
    return testAuth

# Since Slacker does not Cache.. populate some reused lists
def bootstrapKeyValues():
    global users, channels, groups, dms
    users = slack.users.list().data['members']
    print("Found {0} Users".format(len(users)))
    sleep(1)
    
    channels = slack.channels.list().data['channels']
    print("Found {0} Public Channels".format(len(channels)))
    sleep(1)

    groups = slack.groups.list().data['channels']
    print("Found {0} Private Channels or Group DMs".format(len(groups)))
    sleep(1)

    dms = slack.im.list().data['channels']
    print("Found {0} 1:1 DM conversations\n".format(len(dms)))
    sleep(1)

    getUserMap()

# Returns the conversations to download based on the command-line arguments
def selectConversations(allConversations, commandLineArg, filter, prompt):
    global args
    if args.excludeArchived:
        allConversations = [ conv for conv in allConversations if not conv["is_archived"] ]
    if args.ignoreChannels:
        convs = []
        for conv in allConversations:
            if not conv['is_im'] and conv["name"] not in args.ignoreChannels:
                convs.append(conv)
        allConversations = convs
    if isinstance(commandLineArg, list) and len(commandLineArg) > 0:
        return filter(allConversations, commandLineArg)
    elif commandLineArg != None or not anyConversationsSpecified():
        if args.prompt:
            return prompt(allConversations)
        else:
            return allConversations
    else:
        return []

# Returns true if any conversations were specified on the command line
def anyConversationsSpecified():
    global args
    return args.publicChannels != None or args.groups != None or args.directMessages != None

# This method is used in order to create a empty Channel if you do not export public channels
# otherwise, the viewer will error and not show the root screen. Rather than forking the editor, I work with it.
def dumpDummyChannel():
    channelName = channels[0]['name']
    mkdir( channelName )
    fileDate = '{:%Y-%m-%d}'.format(datetime.today())
    outFileName = u'{room}/{file}.json'.format( room = channelName, file = fileDate )
    writeMessageFile(outFileName, [])

def downloadFiles(token, skip_thumbnails: bool = False):
    """
    Iterate through all json files, downloads files stored on files.slack.com and replaces the link with a local one

    Args:
        jsonDirectory: folder where the json files are in, will be searched recursively
    """
    print("Starting to download files Function")
    for root, subdirs, files in os.walk("."):
        for filename in files:
            if not filename.endswith('.json'):
                continue
            print(f'Processing file: {filename}')
            filePath = os.path.join(root, filename)
            data = []
            with open(filePath) as inFile:
                data = json.load(inFile)
                for msg in data:
                    for slackFile in msg.get("files", []):
                        print("Found file: %s" % slackFile.get("name"))
                        # Skip deleted files
                        if slackFile.get("mode") == "tombstone":
                            print("Skipping deleted file: %s" % slackFile.get("name"))
                            continue

                        for key, value in slackFile.items():
                            # Find all entries referring to files on files.slack.com
                            if not isinstance(value, str) or not value.startswith("https://files.slack.com/") or key == 'url_private_download':
                                continue

                            # Skip thumbnails
                            if skip_thumbnails and key.lower().startswith('thumb'):
                                continue

                            url = urlparse(value)

                            localFile = os.path.join("files.slack.com", url.path[1:])  # Need to discard first "/" in URL, because:
                                # "If a component is an absolute path, all previous components are thrown away and joining continues
                                # from the absolute path component."
                            print("Downloading %s, saving to %s" % (url.geturl(), localFile))

                            # Create folder structure
                            os.makedirs(os.path.dirname(localFile), exist_ok=True)

                            # Check if file already downloaded, with same size
                            if os.path.exists(localFile) and os.path.getsize(localFile) == slackFile.get("size", -1):
                                print("Skipping already downloaded file: %s" % localFile)
                                continue

                            # Download files
                            headers = {"Authorization": "Bearer %s" % token}
                            r = requests.get(url.geturl(), headers=headers)
                            r.raise_for_status()
                            with open(localFile, 'wb') as f:
                                f.write(r.content)

                            # Replace URL in data - suitable for use with slack-export-viewer if files.slack.com is linked
                            slackFile[key] = "../../static/files.slack.com%s" % url.path

            # Save updated data to json file
            with open(filePath, "w") as outFile:
                json.dump(data, outFile, indent=4, sort_keys=True)

            print("Replaced all files in %s" % filePath)

def finalize():
    os.chdir('..')
    if zipName:
        shutil.make_archive(zipName, 'zip', outputDirectory, None)
        shutil.rmtree(outputDirectory)
    exit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Export Slack history')

    parser.add_argument('--token', required=True, help="Slack API token")
    parser.add_argument('--zip', help="Name of a zip file to output as")

    parser.add_argument(
        '--dryRun',
        action='store_true',
        default=False,
        help="List the conversations that will be exported (don't fetch/write history)")

    parser.add_argument(
        '--publicChannels',
        nargs='*',
        default=None,
        metavar='CHANNEL_NAME',
        help="Export the given Public Channels")

    parser.add_argument(
        '--ignoreChannels',
        nargs='*',
        default=None,
        metavar='IGNORE_CHANNEL_NAME',
        help='Ignore the given Public Channels'
    )

    parser.add_argument(
        '--groups',
        nargs='*',
        default=None,
        metavar='GROUP_NAME',
        help="Export the given Private Channels / Group DMs")

    parser.add_argument(
        '--directMessages',
        nargs='*',
        default=None,
        metavar='USER_NAME',
        help="Export 1:1 DMs with the given users")

    parser.add_argument(
        '--prompt',
        action='store_true',
        default=False,
        help="Prompt you to select the conversations to export")

    parser.add_argument(
        '--downloadSlackFiles',
        action='store_true',
        default=False,
        help="Downloads files from files.slack.com for local access, stored in 'files.slack.com' folder. "
            "Link this folder inside slack-export-viewer/slackviewer/static/ to have it work seamless with slack-export-viewer")

    parser.add_argument(
        '--skipThumbnails',
        action='store_true',
        default=False,
        help="Skip downloading thumbnails"
    )

    parser.add_argument(
        '--excludeArchived',
        action='store_true',
        default=False,
        help="Do not export channels that have been archived")

    parser.add_argument(
        '--excludeNonMember',
        action='store_true',
        default=False,
        help="Only export public channels if the user is a member of the channel")

    args = parser.parse_args()

    users = []
    channels = []
    groups = []
    dms = []
    userNamesById = {}
    userIdsByName = {}

    slack = Slacker_Wrapper(args.token)
    testAuth = doTestAuth()
    tokenOwnerId = testAuth['user_id']

    bootstrapKeyValues()

    dryRun = args.dryRun
    zipName = args.zip

    outputDirectory = "{0}-slack_export".format(datetime.today().strftime("%Y%m%d-%H%M%S"))
    mkdir(outputDirectory)
    os.chdir(outputDirectory)

    if not dryRun:
        dumpUserFile()
        dumpChannelFile()

    selectedChannels = selectConversations(
        channels,
        args.publicChannels,
        filterConversationsByName,
        promptForPublicChannels)
    if args.excludeNonMember:
        selectedChannels  = [ channel for channel in selectedChannels if channel["is_member"] ]

    selectedGroups = selectConversations(
        groups,
        args.groups,
        filterConversationsByName,
        promptForGroups)

    selectedDms = selectConversations(
        dms,
        args.directMessages,
        filterDirectMessagesByUserNameOrId,
        promptForDirectMessages)

    if len(selectedChannels) > 0:
        fetchPublicChannels(selectedChannels)

    if len(selectedGroups) > 0:
        if len(selectedChannels) == 0:
            dumpDummyChannel()
        fetchGroups(selectedGroups)

    if len(selectedDms) > 0:
        fetchDirectMessages(selectedDms)

    if args.downloadSlackFiles:
        print("Starting to download files")
        downloadFiles(args.token, args.skipThumbnails)

    finalize()
