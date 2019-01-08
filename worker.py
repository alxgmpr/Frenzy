from threading import Thread
from mongoengine import *
from pymongo import errors
import requests
import json
from time import sleep
from datetime import datetime, timedelta
import urllib3
from models import Sale

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class Worker(Thread):
    def __init__(self, configuration=None):
        super().__init__()
        self.configuration = configuration

    def get_initial_scrape(self):
        print('getting initial scrape')
        r = requests.get(
            url=self.configuration['frenzy_endpoint'],
            verify=False
        )
        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError:
            print('[error] bad status {} on initial scrape'.format(r.status_code))
            return False
        try:
            j = r.json()
        except json.JSONDecodeError:
            print('[error] couldnt decode json')
            return False
        print('initially found {} flashsales'.format(len(j['flashsales'])))
        for idx, fs in enumerate(j['flashsales']):
            try:
                im_url = fs['image_urls'][0]
            except IndexError:
                im_url = None
            new_sale = Sale(
                shopify_id=fs['id'],
                handle=fs['password'],
                description=fs['description'],
                image_url=im_url,
                title=fs['title'],
                start_time=datetime.strptime(fs['started_at'].split('.')[0], '%Y-%m-%dT%H:%M:%S'),
                is_hidden=fs['hidden'],
                is_sold_out=fs['sold_out'],
                is_pickup=fs['pickup'],
                shipping_message=fs['shipping_message']
            ).save()
            if not new_sale:
                print('[error] couldnt save new sale to database')
                return False
        return True

    def scrape_for_new_sales(self):
        print('checking for new sales')
        r = requests.get(
            url=self.configuration['frenzy_endpoint'],
            verify=False
        )
        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError:
            print('[error] bad status {} on scrape'.format(r.status_code))
            return False
        try:
            j = r.json()
        except json.JSONDecodeError:
            print('[error] couldnt decode json')
            return False
        for idx, fs in enumerate(j['flashsales']):
            id_to_check = fs['id']
            if not Sale.objects(shopify_id=id_to_check):
                print('!!! NEW SALE FOUND !!!')
                print('<<<')
                print('[{}] [{} ] [{}]'.format(str(fs['id']).ljust(10), fs['password'], fs['title'].ljust(30)))
                print('[count: {}] [pickup: {}] [{}]'.format(str(fs['products_count']).ljust(3),
                                                             str(fs['pickup']).ljust(5), fs['shipping_message']))
                print('[deal: {}]'.format(fs['deal_sale']))
                for fs_prod in fs['product_details']:
                    print('-> [{}] $[{}]'.format(fs_prod['title'].ljust(30), fs_prod['price_range']['min']))
                print('>>> {}\n'.format(idx))
                try:
                    im_url = fs['image_urls'][0]
                except IndexError:
                    im_url = None
                #
                new_sale = Sale(
                    shopify_id=fs['id'],
                    handle=fs['password'],
                    image_url=im_url,
                    title=fs['title'],
                    start_time=datetime.strptime(fs['started_at'].split('.')[0], '%Y-%m-%dT%H:%M:%S'),
                    is_hidden=fs['hidden'],
                    is_sold_out=fs['sold_out'],
                    is_pickup=fs['pickup'],
                    shipping_message=fs['shipping_message']
                ).save()
                if not new_sale:
                    print('[error] couldnt save new sale to database')
                    return False
                self.fire_discord(new_sale, new=True)
                new_sale.has_sent_new_alert = True
                new_sale.save()
        return True

    def fire_discord(self, sale, new=False):
        if not self.configuration['send_discord']:
            return True
        embed = {
            "title": "LINK: {}".format(sale.title),
            "url": "https://frenzy.sale/{}".format(sale.handle),
            "color": 8311585,

            "timestamp": datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            "footer": {
                "text": "Frenzy Monitor v0.0.1"
            },
            "thumbnail": {
                "url": sale.image_url if sale.image_url else ""
            },
            "author": {
                "name": sale.title
            },
            "fields": [
                {
                    "name": "Details",
                    "value": sale.description if sale.description else "None"
                },
                {
                    "name": "Sold Out?",
                    "value": str(sale.is_sold_out),
                    "inline": True
                },
                {
                    "name": "Pickup?",
                    "value": str(sale.is_pickup),
                    "inline": True
                },
                {
                    "name": "Shipping Details",
                    "value": sale.shipping_message if sale.shipping_message else "None"
                },
                {
                    "name": "Release Date",
                    "value": str(sale.start_time)
                }
            ]
        }
        content = "A new Frenzy sale was added" if new else "A Frenzy sale is close to dropping"
        r = requests.post(
            self.configuration['discord_webhook'],
            json={
                "content": content,
                "embeds": [embed]
            },
            verify=False
        )
        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError:
            print('[error firing discord] code {}'.format(r.status_code))
            print(r.text)
            try:
                j = r.json()
                try:
                    print('[error] rate limited - sleeping for {}'.format(int(j['retry_after'] / 1000) + 1))
                    sleep(int(j['retry_after'] / 1000) + 1)
                    self.fire_discord(sale, new)
                except (KeyError, IndexError, ValueError):
                    return False
            except json.JSONDecodeError:
                return False
        return True

    def check_for_upcoming_sales(self):
        if not self.configuration['warn_before_drop']:
            return True
        print('checking for upcoming sales')
        for sale in Sale.objects:
            if sale.has_sent_time_alert:
                pass
            diff_mins = ((sale.start_time - datetime.now()).total_seconds()-21600)/60
            if 0 < diff_mins <= self.configuration['minutes_before_warning']:
                print('{} is coming up in less than {} minutes'.format(sale.title, self.configuration['minutes_before_warning']))
                self.fire_discord(sale)
                sale.has_sent_time_alert = True
                sale.save()
        return True

    def run(self):
        try:
            print('connecting to mongo server')
            connect(host=self.configuration['mongo_uri'])
            sleep(10)
        except errors.ServerSelectionTimeoutError:
            print('[error] couldnt connect to the mongo server')
            return False
        print('connected to mongo server')

        print('clearing mongo documents')
        Sale.objects.delete()

        print('running scrape sequence')
        if not self.get_initial_scrape():
            print('breaking on initial scrape')
            return False

        print('entering loop')
        while True:
            if not self.scrape_for_new_sales():
                print('breaking on scrape for new')
                break
            if not self.check_for_upcoming_sales():
                print('breaking on check for upcoming')
                break
            sleep(self.configuration['poll_time'])

        print('terminating')
        return True
