from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.email import EmailOperator
from airflow.operators.dummy import DummyOperator

BASE_PATH= "/opt/airflow/dags/"
dag =  DAG(
    'data_ds',
    default_args={
        'email': ['cuongthanhhk@gmail.com'],
        'email_on_failure': False,
        'retries': 1,
        'retry_delay': timedelta(minutes=1),
    },
    description='A simple DAG sample ',
    schedule_interval="@once",
    start_date=datetime(2023, 6, 23), # Start date
    tags=['ds'],
)

start_task = DummyOperator(
    task_id='start_task',
    dag=dag,
)


t1 = BashOperator(
    task_id='update_data',
    bash_command=f'python3 {BASE_PATH}crawl/update_data.py',
    dag = dag
)

t2 = BashOperator(
    task_id='index_data',
    bash_command=f'python3 {BASE_PATH}index_es/index_to_es.py',
    # bash_command='echo t2 running',
    retries=3,
    dag = dag
)

t3 = BashOperator(
    task_id='train_model',
    bash_command=f'python3 {BASE_PATH}model/light_gbm.py',
    dag = dag
)

send_email_task = EmailOperator(
    task_id='send_email_task',
    to='cuongthanhhk@gmail.com',  # Email người nhận
    subject='Airflow Email Example',
    html_content='<p>This is the HTML body of the email</p>',
    files=[f'{BASE_PATH}data/output_model_metrics.txt'],
    dag=dag,
)

end_task = DummyOperator(
    task_id='end_task',
    dag=dag,
)

start_task >> t1 >> t2 >> end_task
t1 >> t3 >> send_email_task >> end_task
