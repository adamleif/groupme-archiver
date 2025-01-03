import argparse
import glob
import json
import os
import requests
import sys
from tqdm import tqdm
from time import sleep 

from tabulate import tabulate


def list_groups(args):
    headers = {'Content-Type': 'application/json'}
    page_num = 1
    listing_complete = False

    chats = []
    while not listing_complete:
        params = {
            'token': args.token,
            'omit':  'memberships',
            'page':  page_num
        }
        r = requests.get('https://api.groupme.com/v3/groups',
                         headers=headers, params=params)

        current_chats = json.loads(r.content)

        for chat in current_chats['response']:
            chats.append((chat['name'], chat['id'], chat['messages']['count']))

        page_num += 1
        if len(current_chats['response']) == 0:
            listing_complete = True

    return chats


def list_dms(args):
    headers = {'Content-Type': 'application/json'}
    page_num = 1
    listing_complete = False

    chats = []
    while not listing_complete:
        params = {
            'token': args.token,
            'page':  page_num
        }
        r = requests.get('https://api.groupme.com/v3/chats',
                         headers=headers, params=params)

        current_chats = json.loads(r.content)

        for chat in current_chats['response']:
            chats.append((
                        chat['other_user']['name'],
                        chat['other_user']['id'],
                        chat['messages_count']
                        ))

        page_num += 1
        if len(current_chats['response']) == 0:
            listing_complete = True

    return chats


def fetch_group_messages(args):
    params = {
        'token': args.token
    }
    url = 'https://api.groupme.com/v3/groups/%s' % (args.group_chat_id)
    
    r = requests.get(url, params=params)

    people = {}
    messages = []
    group_info = {}
    all_attachments = []

    response = json.loads(r.content)['response']

    group_info['name'] = response['name']
    group_info['description'] = response['description']
    group_info['image_url'] = response['image_url']
    group_info['created_at'] = response['created_at']

    for member in response['members']:
        people[member['user_id']] = {'name': member['nickname']}
        if args.save_global_avatars:
            people[member['user_id']]['avatar_url'] = member['image_url']
        else:
            people[member['user_id']]['avatar_url'] = None

    last_message_id = args.last_message_id
    earliest_time = sys.maxsize

    pbar = tqdm() 
    completed = False

    def get_messages():
        try:
            nonlocal params 
            nonlocal people 
            nonlocal messages 
            nonlocal group_info 
            nonlocal all_attachments
            nonlocal last_message_id 
            nonlocal earliest_time
            nonlocal pbar 
            nonlocal completed 

            if last_message_id:
                pbar.write(f"Starting from last_message_id: {last_message_id}")
                params = {
                        'token': args.token,
                        'before_id': last_message_id,
                        'limit': args.num_messages_per_request
                    }
                earliest_time = last_message_id[:10]  # pull the UNIX timestamp from the id
            
            url = 'https://api.groupme.com/v3/groups/%s/messages' % (
                args.group_chat_id)
            r = requests.get(url, params=params)

            if not r.content: 
                return messages, people, group_info, all_attachments
            
            curr_messages = json.loads(r.content)

            # TODO Check for validity of request
            num_total_messages = curr_messages['response']['count']
            num_fetched_messages = 0
            curr_messages = curr_messages['response']['messages']

            tqdm.write("Fetching %d messages..." % (num_total_messages))
            pbar.total = num_total_messages

            while not completed:  
                sleep(0.35)  # add in a delay to prevent a 429 error
                num_fetched_messages += len(curr_messages)
                pbar.update(len(curr_messages))

                if curr_messages[-1]['id'] == last_message_id:
                    completed = True 
                    
                for message in curr_messages:
                    if message['sender_id'] not in people:
                        people[message['sender_id']] = {
                            'name': message['name'],
                            'avatar_url': message['avatar_url']
                        }
                    if not args.save_global_avatars and \
                    people[message['sender_id']]['avatar_url'] is None:
                        people[message['sender_id']]['avatar_url'] = \
                            message['avatar_url']

                    for att in message['attachments']:
                        if att['type'] == 'image' or \
                        att['type'] == 'video' or \
                        att['type'] == 'linked_image':
                            all_attachments.append(att['url'])
                    # print("[%s] %s : %s" % (
                    #    message['created_at'], message['name'], message['text']))
                    m = {
                        'id': message['id'],
                        'author': message['sender_id'],
                        'created_at': message['created_at'],
                        'text': message['text'],
                        'favorited_by': message['favorited_by'],
                        'attachments': message['attachments']
                    }

                    m_time = m['created_at']
                    if m not in messages[-100:0] and not m_time >= earliest_time:
                        messages.append(m)
                        earliest_time = m_time
                    elif m_time < earliest_time:  # if it was in messages but is somehow still the earliest
                        earliest_time = m_time
                    
                last_message_id = curr_messages[-1]['id']

                params = {
                        'token': args.token,
                        'before_id': last_message_id,  # 
                        'limit': args.num_messages_per_request
                    }
                url = 'https://api.groupme.com/v3/groups/%s/messages' % (
                    args.group_chat_id)
                
                def get_message_batch():
                    nonlocal completed 

                    r = requests.get(url, params=params)

                    if not r.content: 
                        completed = True 
                        return 
                    
                    _curr_messages = json.loads(r.content)

                    # TODO Check for validity of request
                    try:
                        return _curr_messages['response']['messages']
                    except Exception as e:
                        pbar.set_description("Request error, sleeping for 30 seconds") 
                        sleep(30)
                        pbar.set_description("")

                        return get_message_batch()

                curr_messages = get_message_batch() 

            pbar.close()

            return messages, people, group_info, all_attachments
        except KeyboardInterrupt as e:
            raise e
        except Exception as e:
            tqdm.write(f"Ran into an issue:\n{e}\n; resuming from {last_message_id}")
            return get_messages()
        
    return get_messages()


def fetch_direct_messages(args):
    params = {
        'token': args.token,
        'other_user_id': args.direct_chat_id
    }
    url = 'https://api.groupme.com/v3/direct_messages'
    r = requests.get(url, params=params)

    people = {}
    messages = []
    group_info = {}

    curr_messages = json.loads(r.content)

    # TODO Check for validity of request
    num_total_messages = curr_messages['response']['count']
    num_fetched_messages = 0
    curr_messages = curr_messages['response']['direct_messages']
    all_attachments = []

    print("Fetching %d messages..." % (num_total_messages))
    pbar = tqdm(total=num_total_messages)
    while num_fetched_messages < num_total_messages:
        num_fetched_messages += len(curr_messages)
        pbar.update(len(curr_messages))
        for message in curr_messages:
            if message['sender_id'] not in people:
                people[message['sender_id']] = {
                    'name': message['name'],
                    'avatar_url': message['avatar_url']
                }

            for att in message['attachments']:
                if att['type'] == 'image' or \
                   att['type'] == 'video' or \
                   att['type'] == 'linked_image':
                    all_attachments.append(att['url'])
            # print("[%s] %s : %s" % (
            #    message['created_at'], message['name'], message['text']))
            messages.append({
                'author': message['sender_id'],
                'created_at': message['created_at'],
                'text': message['text'],
                'favorited_by': message['favorited_by'],
                'attachments': message['attachments']
            })
        last_message_id = curr_messages[-1]['id']

        params = {
            'token': args.token,
            'other_user_id': args.direct_chat_id,
            'before_id': last_message_id,
            'limit': args.num_messages_per_request
        }
        url = 'https://api.groupme.com/v3/direct_messages'
        r = requests.get(url, params=params)

        if r.status_code == 304:
            break
        curr_messages = json.loads(r.content)

        # TODO Check for validity of request
        curr_messages = curr_messages['response']['direct_messages']

    pbar.close()
    messages = list(reversed(messages))

    group_info['name'] = people[args.direct_chat_id]['name']
    group_info['image_url'] = people[args.direct_chat_id]['avatar_url']

    return messages, people, group_info, all_attachments


def download_attachments(attachments_url_file, output_dir = None): 
    if not output_dir: 
        output_dir = "/".join(attachments_url_file.split("/")[:-1])
    
    with open(attachments_url_file, encoding='utf-8') as fp:
        all_attachments = json.load(fp)

    for att_url in tqdm(all_attachments):
        file_name = att_url.split('/')[-1]
        att_path = 'attachments/%s.%s' % (file_name, "*")
        att_full_path = os.path.join(output_dir, att_path)
        if len(glob.glob(att_full_path)) == 0:
            r = requests.get(att_url)
            img_type = r.headers['content-type'].split('/')[1]
            att_path = 'attachments/%s.%s' % (file_name, img_type)
            att_full_path = os.path.join(output_dir, att_path)

            with open(att_full_path, 'wb') as fp:
                fp.write(r.content)
        

def main():
    parser = argparse.ArgumentParser(description="""GroupMe chats archiver.
        By default, the app will list all of your chats that are currently
        active.
        """)

    parser.add_argument('--token', '-t', required=True,
                        help="GroupMe Developer Token")

    parser.add_argument('--group-chat-id', '-g', dest="group_chat_id",
                        help="Group chat ID to archive")
    parser.add_argument('--direct-chat-id', '-d', dest="direct_chat_id",
                        help="Direct Message chat ID to archive")

    parser.add_argument('--num-messages-per-request', '-n', default=20,
                        dest='num_messages_per_request',
                        help="Number of messages in each request. Max: 100.")
    parser.add_argument('--output-dir', '-o', dest="output_dir",
                        help="Output directory to store archived content")
    parser.add_argument('--save-global-avatars', action='store_true',
                        dest='save_global_avatars',
                        help="Use global avatars instead of " +
                             "chat specific user avatars")
    parser.add_argument('--last-message-id', '-l', dest="last_message_id",
                        help="ID of last message at which to resume/begin archiving")
    parser.add_argument('--download-attachments', '-a', dest="download_attachments", 
                        action='store_true', help="Whether all attachments should be downloaded")
    parser.add_argument('--skip-archive', '-s', dest="skip_archive", 
                        action='store_true', help="Whether archive process should be skipped" + 
                        "while only other steps (e.g. attachment downloading) occur")
    

    args = parser.parse_args()

    if not args.group_chat_id and not args.direct_chat_id and not args.skip_archive:
        print("Group chats")
        print("===========")
        chats = list_groups(args)
        table_headers = ["Chat Name", "ID", "Number of messages"]
        print(tabulate(chats, headers=table_headers))

        print("")
        print("Direct Messages")
        print("===============")
        chats = list_dms(args)
        table_headers = ["Chat Name", "ID", "Number of messages"]
        print(tabulate(chats, headers=table_headers))
    else:        
        if not args.skip_archive:
            if args.group_chat_id:
                messages, people, group_info, all_attachments = \
                    fetch_group_messages(args)
            else:
                messages, people, group_info, all_attachments = \
                    fetch_direct_messages(args)  

            if not output_dir:
                output_dir = group_info['name']
                output_dir = output_dir.replace('/', ' ')

            os.makedirs(output_dir, exist_ok=True)

            print("\nFetching avatars...")
            avatars_path = os.path.join(output_dir, 'avatars/')
            os.makedirs(avatars_path, exist_ok=True)
            for k, v in tqdm(people.items()):
                url = v['avatar_url']
                if url:
                    r = requests.get("%s.avatar" % (url))
                    img_type = r.headers['content-type'].split('/')[1]
                    avatar_path = os.path.join(avatars_path,
                                            '%s.avatar.%s' % (k, img_type))
                    with open(avatar_path, 'wb') as fp:
                        fp.write(r.content)

            print("\nPeople:")
            table_headers = {
                "id": "ID",
                "name": "Name",
                "avatar_url": "Avatar URL"
            }
            print(tabulate([dict({'id': k}, **v) for (k, v) in people.items()],
                        headers=table_headers))

            # Save everything
            contents = os.listdir(output_dir)

            people_fn = "people"
            messages_fn = "messages"
            group_info_fn = "group_info"

            ps = len([p for p in contents if "people" in p])
            ms = len([m for m in contents if "message" in m])

            if ps > 0: people_fn += str(ps)
            if ms > 0: messages_fn += str(ms) 

            # TODO: handle combining multiples and removing duplicates
            people_file = os.path.join(output_dir, f"{people_fn}.json")
            messages_file = os.path.join(output_dir, f"{messages_fn}.json")
            group_info_file = os.path.join(output_dir, f"{group_info_fn}.json")

            # Save people
            with open(people_file, 'w', encoding='utf-8') as fp:
                json.dump(people, fp, ensure_ascii=False, indent=2)

            # Save messages
            with open(messages_file, 'w', encoding='utf-8') as fp:
                messages = list(reversed(messages))
                json.dump(messages, fp, ensure_ascii=False, indent=2)

            # Save group information
            with open(group_info_file, 'w', encoding='utf-8') as fp:
                json.dump(group_info, fp, ensure_ascii=False, indent=2)

            print("\nFetching attachments...")
            attachments_path = os.path.join(output_dir, 'attachments/')
            os.makedirs(attachments_path, exist_ok=True)

            all_attachments_fn = "attachments_urls"
            aS = len([a for a in os.listdir(attachments_path) if "attachments_urls" in a])
               
            if aS: all_attachments_fn += str(aS)

            # as a storage solution, rather than initially downloading all attachments,
            # just store a text file with them instead for later downloading
            all_attachments_file = os.path.join(attachments_path, f"{all_attachments_fn}.json")            
            with open(all_attachments_file, 'w', encoding='utf-8') as fp:                
                json.dump(all_attachments, fp, ensure_ascii=False, indent=2)
        else:
            params = {
                'token': args.token
                }
            url = 'https://api.groupme.com/v3/groups/%s' % (args.group_chat_id)
    
            r = requests.get(url, params=params)
            response = json.loads(r.content)['response']

            group_name = response['name']  

            if not args.output_dir:
                output_dir = group_name
                output_dir = output_dir.replace('/', ' ')

            attachments_path = os.path.join(output_dir, 'attachments/')
            all_attachments_file = os.path.join(attachments_path, f"attachments_urls.json")            

        if args.download_attachments:
            download_attachments(all_attachments_file, output_dir=output_dir)

if __name__ == '__main__':
    main()
