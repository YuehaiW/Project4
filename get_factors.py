import pymysql
import numpy as np
import pandas as pd
import statsmodels.api as sm

from tqdm import tqdm


def ewma(window, half_life):
    """给出指数移动平均的权重"""
    lamb = 0.5 ** (1 / half_life)
    weights = np.array([lamb ** (window - i) for i in range(window)])
    return weights / np.sum(weights)


def MAD_winsorize(x, multiplier=5):
    """MAD去除极端值"""
    med = np.nanmedian(x)
    x_MAD = np.nanmedian(np.abs(x - med))
    upper = med + multiplier * x_MAD
    lower = med - multiplier * x_MAD
    x[x > upper] = upper
    x[x < lower] = lower
    return x


def calc_beta(returns, hist_ret, index_rets):
    """
    计算Beta
    :param returns:  指数成分股的日收益率，有三列date, code, daily returns
    :param hist_ret: 所有在指数中出现过的股票的日收益率，索引为date，列名为code，值为收益率
    :param index_rets:  市场组合的日收益率
    """
    trade_dt = hist_ret.index
    dt = returns.date.unique()
    window, half_life = 252, 63
    W = ewma(window, half_life)
    beta_list = []

    for i in tqdm(range(len(dt))):
        end_ind = np.where(trade_dt == dt[i])[0] - 1
        end = trade_dt[end_ind[0]]
        start = trade_dt[end_ind[0] - window + 1]

        mp = index_rets.loc[start:end, :]
        X = sm.add_constant(mp)
        X_mat = X.to_numpy()
        codes = returns[returns.date == dt[i]].code
        tmp = hist_ret.loc[start:end, codes]
        # 有缺失值和没有缺失值的数据分开处理
        y1, W1 = tmp.dropna(axis=1), np.diag(W)
        params = np.linalg.pinv(X_mat.T @ W1 @ X_mat) @ X_mat.T @ W1 @ y1
        beta1 = params.iloc[1, :]

        lack = tmp.columns[tmp.isna().any()]
        beta2_list = []
        for code in lack:
            tmp2 = tmp.loc[:, code]
            tmp2 = pd.concat([X, tmp2], axis=1)
            tmp2['weights'] = W
            tmp2.dropna(inplace=True)
            # 有NaN则删除后用剩余值计算，少于63天不计算
            if len(tmp2) < half_life:
                continue
            y2 = tmp2[code]
            W2 = np.diag(tmp2['weights'])
            X2 = tmp2.iloc[:, :2].to_numpy()
            params = np.linalg.pinv(X2.T @ W2 @ X2) @ X2.T @ W2 @ y2
            beta2_list.append(params[1])

        beta2 = pd.Series(beta2_list, index=lack)
        beta_list.append(pd.concat([beta1, beta2]).sort_index())
    # 返回一个储存Beta值的数据框
    return pd.concat(beta_list, axis=0)


def calc_momentum(returns, benchmark):
    weights = ewma(window=484, half_life=126)
    weights = weights.reshape(-1, 1)
    RSTR = pd.DataFrame(0, index=returns.index[503:len(returns)], columns=returns.columns)
    for i in range(len(returns) - 503):
        tmp = returns.iloc[i:(i + 484), :].copy()
        # tmp = tmp.loc[:, tmp.isnull().sum(axis=0) / 252 <= 0.2].fillna(0.)
        rf = benchmark.iloc[i:(i + 484), :].copy()
        RSTR.iloc[i, :] = np.sum(weights * (np.log(1 + tmp).values - np.log(1 + rf).values), axis=0)
    momentum = pd.melt(RSTR)
    return RSTR


def get_size(code, start, end):
    # 获取数据
    conn = pymysql.connect(
        host="192.168.7.93",
        user="quantchina",
        password="zMxq7VNYJljTFIQ8",
        database="wind",
        charset="gbk"
    )
    cursor = conn.cursor()

    query = """
                    select TRADE_DT, S_INFO_WINDCODE, S_VAL_MV
                    from ASHAREEODDERIVATIVEINDICATOR
                    where TRADE_DT between '{start}' and '{end}' and 
                          S_INFO_WINDCODE in (select distinct S_CON_WINDCODE
                                              from AINDEXMEMBERS
                                              where S_INFO_WINDCODE = '{code}' and S_CON_INDATE <= '{end}' and 
                                               (S_CON_OUTDATE >= '{start}' or S_CON_OUTDATE is null) )
                    order by TRADE_DT, S_INFO_WINDCODE
                   """.format(code=code, start=start, end=end)
    cursor.execute(query)
    data = cursor.fetchall()
    df = pd.DataFrame(data, columns=['date', 'code', 'cap'])
    df['cap'] = df['cap'].astype(float)
    df['lncap'] = np.log(df['cap'])

    return df[['date', 'code', 'lncap']]
