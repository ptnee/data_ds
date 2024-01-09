from datetime import datetime

from elasticsearch import Elasticsearch, helpers
# import toml
import pandas as pd
import os

BASE_PATH = "/opt/airflow/dags/"

es_hosts = [
    # "http://localhost:9200"
    "http://elasticsearch:9200"
    # "http://172.18.0.2:9200"

]
index_name = 'test_data_ds'

"""
curl -X DELETE "http://elastic:Citigo2025@10.24.103.2:9200/fr_hdfs"

curl -X PUT "http://elastic:Citigo2025@10.24.103.2:9200/fr_hdfs?pretty" -H 'Content-Type: application/json' -d'
{
  "settings": {
    "index": {
      "number_of_shards": 1,
      "number_of_replicas": 3
    }
  }
}
'
"""

def remove_accents(input):
    s1 = u'ÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝàáâãèéêìíòóôõùúýĂăĐđĨĩŨũƠơƯưẠạẢảẤấẦầẨẩẪẫẬậẮắẰằẲẳẴẵẶặẸẹẺẻẼẽẾếỀềỂểỄễỆệỈỉỊịỌọỎỏỐốỒồỔổỖỗỘộỚớỜờỞởỠỡỢợỤụỦủỨứỪừỬửỮữỰựỲỳỴỵỶỷỸỹ'
    s0 = u'AAAAEEEIIOOOOUUYaaaaeeeiioooouuyAaDdIiUuOoUuAaAaAaAaAaAaAaAaAaAaAaAaEeEeEeEeEeEeEeEeIiIiOoOoOoOoOoOoOoOoOoOoOoOoUuUuUuUuUuUuUuYyYyYyYy'
    s = ''
    for c in input:
        if c in s1:
            s += s0[s1.index(c)]
        else:
            s += c
    return s.lower()


def read_data(path):
    # df = pd.read(path)
    df = pd.read_csv(path)
    return df


def index_data(product):
    for es_host in es_hosts:
        print(f"Indexing into {es_host} with index {index_name}")
        es_client = Elasticsearch(hosts=[es_host])
        result = []
        count = 0
        num = 0
        for index, row in product.iterrows():
            doc = row
            # timestamp = doc["GAME_DATE_EST"]
            # timestamp_value = datetime.fromisoformat(timestamp).timestamp()
            # doc['timestamp'] = timestamp_value
            doc = doc.to_dict()
            result.append(doc)
            count += 1
            if count == 1000:
                helpers.bulk(es_client, result, index=index_name, request_timeout=200)
                count = 0
                result = []
                num += 1
                print('batch', num)
        if len(result) > 0:
            print(num)
            helpers.bulk(es_client, result, index=index_name, request_timeout=200)
        print('done')


def delete_data(path):
    if os.path.exists(path):
        os.remove(path)
    else:
        print("The file does not exist")


# config = toml.load('config.toml')
df = read_data(f"{BASE_PATH}data/new_games.csv")
print(df)
df = df.dropna()
index_data(df)
