import pandas as pd

pd.set_option('display.max_columns', 500)

from sklearn.metrics import accuracy_score
from sklearn.metrics import roc_auc_score
from sklearn.metrics import roc_curve
from sklearn.model_selection import StratifiedKFold

import xgboost as xgb
print('XGB version:', xgb.__version__)

import lightgbm as lgb
from lightgbm import early_stopping
from lightgbm import log_evaluation
print('LGB version:', lgb.__version__)

from tqdm import tqdm

import pandas as pd
import numpy as np

df = pd.read_csv("opt/airflow/dags/data/transformed.csv")

latest_season = df['SEASON'].unique().max()

train = df[df['SEASON'] < (latest_season)]
test = df[df['SEASON'] >= (latest_season - 1)]

train.to_csv("opt/airflow/dags/data/train.csv",index=False)
test.to_csv("opt/airflow/dags/data/test.csv",index=False)

DATAPATH = "opt/airflow/dags/"
train = pd.read_csv(DATAPATH + "train.csv")
test = pd.read_csv(DATAPATH + "test.csv")

predict = predict = np.ones((train.shape[0],))
true = train['TARGET']

accuracy_score(true,predict), roc_auc_score(true,predict)

predict = predict = np.ones((test.shape[0],))
true = test['TARGET']

accuracy_score(true,predict), roc_auc_score(true,predict)


def fix_datatypes(df):

    long_integer_fields = ['GAME_ID', 'HOME_TEAM_ID', 'VISITOR_TEAM_ID', 'SEASON']

    for field in long_integer_fields:
        df[field] = df[field].astype('int32')

    for field in df.select_dtypes(include=['int64']).columns.tolist():
        df[field] = df[field].astype('int8')

    for field in df.select_dtypes(include=['float64']).columns.tolist():
        df[field] = df[field].astype('float16')

    return df


train = fix_datatypes(train)
test = fix_datatypes(test)


def add_rolling_means(df, location):

    location_id = location + "_TEAM_ID"

    df = df.sort_values(by = [location_id, 'GAME_DATE_EST'], axis=0, ascending=[True, True,], ignore_index=True)

    feature_list = ['HOME_TEAM_WINS', 'PTS_home', 'FG_PCT_home', 'FT_PCT_home', 'FG3_PCT_home', 'AST_home', 'REB_home']

    if location == 'VISITOR':
        feature_list = ['HOME_TEAM_WINS', 'PTS_away', 'FG_PCT_away', 'FT_PCT_away', 'FG3_PCT_away', 'AST_away', 'REB_away']

    roll_feature_list = []
    for feature in feature_list:
        roll_feature_name = location + '_' + feature + '_AVG_LAST_' + '5_' + location
        if feature == 'HOME_TEAM_WINS':
            roll_feature_name = location + '_' + feature[5:] + '_AVG_LAST_' + '5_' + location
        roll_feature_list.append(roll_feature_name)
        df[roll_feature_name] = df.groupby(['HOME_TEAM_ID'])[feature].rolling(5, closed= "left").mean().values

    return df


train = add_rolling_means(train, 'HOME')
train = add_rolling_means(train, 'VISITOR')
test = add_rolling_means(test, 'HOME')
test = add_rolling_means(test, 'VISITOR')


target = train['TARGET']
test_target = test['TARGET']

category_columns = ['HOME_TEAM_ID', 'VISITOR_TEAM_ID', 'SEASON', 'HOME_TEAM_WINS', 'PLAYOFF', 'CONFERENCE_x', 'CONFERENCE_y',]

all_columns = train.columns.tolist()
drop_columns = ['TARGET', 'GAME_DATE_EST', 'GAME_ID',]

drop_columns1 = ['HOME_TEAM_WINS', 'PTS_home', 'FG_PCT_home', 'FT_PCT_home', 'FG3_PCT_home', 'AST_home', 'REB_home']
drop_columns2 = ['PTS_away', 'FG_PCT_away', 'FT_PCT_away', 'FG3_PCT_away', 'AST_away', 'REB_away']

drop_columns = drop_columns + drop_columns1
drop_columns = drop_columns + drop_columns2

use_columns = [item for item in all_columns if item not in drop_columns]

train = train[use_columns]
test = test[use_columns]

K_FOLDS = 5
SEED = 13

NUM_BOOST_ROUND = 700
EARLY_STOPPING = 200
LOG_EVALUATION = 100

train_oof = np.zeros((train.shape[0],))
test_preds = 0
train_oof_shap = np.zeros((train.shape[0],train.shape[1]+1))
test_preds_shap = 0

lgb_params = {
            'seed': SEED,
            'verbose': 0,
            'boosting_type': 'gbdt',
            'objective': 'binary',
            'metric': 'auc',

            }

kf = StratifiedKFold(n_splits=K_FOLDS, shuffle=True, random_state=SEED)

for f, (train_ind, val_ind) in tqdm(enumerate(kf.split(train, target))):

    train_df, val_df = train.iloc[train_ind], train.iloc[val_ind]
    train_target, val_target = target[train_ind], target[val_ind]

    train_lgbdataset = lgb.Dataset(train_df, label=train_target,)
    val_lgbdataset = lgb.Dataset(val_df, label=val_target, reference = train_lgbdataset )

    model =  lgb.train(lgb_params,
                       train_lgbdataset,
                       valid_sets=val_lgbdataset,
                       num_boost_round = NUM_BOOST_ROUND,
                       callbacks=[log_evaluation(LOG_EVALUATION),early_stopping(EARLY_STOPPING,verbose=False)],
                      )

    temp_oof = model.predict(val_df)
    temp_oof_shap = model.predict(val_df, pred_contrib=True)

    temp_test = model.predict(test)
    temp_test_shap = model.predict(test, pred_contrib=True)

    train_oof[val_ind] = temp_oof
    test_preds += temp_test/K_FOLDS

    train_oof_shap[val_ind, :] = temp_oof_shap
    test_preds_shap += temp_test_shap/K_FOLDS

    fpr, tpr, thresholds = roc_curve(val_target,temp_oof)
    optimal_idx = np.argmax(tpr - fpr)
    optimal_threshold = thresholds[optimal_idx]
    temp_oof_binary = (temp_oof > optimal_threshold).astype(int)

    print(accuracy_score(val_target, temp_oof_binary), roc_auc_score(val_target, temp_oof))

fpr, tpr, thresholds = roc_curve(target,train_oof)
optimal_idx = np.argmax(tpr - fpr)
optimal_threshold = thresholds[optimal_idx]
train_oof_binary = (train_oof > optimal_threshold).astype(int)

print()
print("Composite Train OOF CV Scores:")
print()
print("Accuracy Score:",accuracy_score(target, train_oof_binary))
print("AUC Score:", roc_auc_score(target, train_oof))
print("Optimal Threshold:", optimal_threshold)


test_preds_binary = (test_preds > optimal_threshold).astype(int)
print()
print("Test data Scores:")
print()
print("Accuracy Score:",accuracy_score(test_target, test_preds_binary))
print("AUC Score:", roc_auc_score(test_target, test_preds))
BASE_PATH= "/opt/airflow/dags/"
val_accuracy = accuracy_score(val_target, (val_predictions > optimal_threshold).astype(int))
val_auc_score = roc_auc_score(val_target, val_predictions)
model.save_model(f'{BASE_PATH}data/output_model.txt')
with open(f'{BASE_PATH}data/output_model_metrics.txt', 'w') as f:
    f.write(f'Validation Accuracy:{val_accuracy}\n')
    f.write(f'Validation AUC Score:{val_auc_score}\n')
