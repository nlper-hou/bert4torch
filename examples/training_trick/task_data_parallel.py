#! -*- coding:utf-8 -*-
# DP示例，这里是把loss放在模型里计算的话，则可以部分缓解负载不均衡的问题

import os
# 也可命令行传入
os.environ["CUDA_VISIBLE_DEVICES"]="0,1"
from bert4torch.tokenizers import Tokenizer
from bert4torch.models import build_transformer_model, BaseModel, BaseModelDP, add_trainer
from bert4torch.snippets import sequence_padding, text_segmentate, ListDataset, seed_everything
import torch.nn as nn
import torch
import torch.optim as optim
import random, os, numpy as np
from torch.utils.data import DataLoader

maxlen = 256
batch_size = 16
config_path = 'F:/Projects/pretrain_ckpt/bert/[google_tf_base]--chinese_L-12_H-768_A-12/bert_config.json'
checkpoint_path = 'F:/Projects/pretrain_ckpt/bert/[google_tf_base]--chinese_L-12_H-768_A-12/pytorch_model.bin'
dict_path = 'F:/Projects/pretrain_ckpt/bert/[google_tf_base]--chinese_L-12_H-768_A-12/vocab.txt'

device = 'cuda' if torch.cuda.is_available() else 'cpu'

# 固定seed
seed_everything(42)

# 建立分词器
tokenizer = Tokenizer(dict_path, do_lower_case=True)

# 加载数据集
class MyDataset(ListDataset):
    @staticmethod
    def load_data(filenames):
        """加载数据，并尽量划分为不超过maxlen的句子
        """
        D = []
        seps, strips = u'\n。！？!?；;，, ', u'；;，, '
        for filename in filenames:
            with open(filename, encoding='utf-8') as f:
                for l in f:
                    text, label = l.strip().split('\t')
                    for t in text_segmentate(text, maxlen - 2, seps, strips):
                        D.append((t, int(label)))
        return D

def collate_fn(batch):
    batch_token_ids, batch_segment_ids, batch_labels = [], [], []
    for text, label in batch:
        token_ids, segment_ids = tokenizer.encode(text, maxlen=maxlen)
        batch_token_ids.append(token_ids)
        batch_segment_ids.append(segment_ids)
        batch_labels.append([label])

    batch_token_ids = torch.tensor(sequence_padding(batch_token_ids), dtype=torch.long, device=device)
    batch_segment_ids = torch.tensor(sequence_padding(batch_segment_ids), dtype=torch.long, device=device)
    batch_labels = torch.tensor(batch_labels, dtype=torch.long, device=device)
    return [batch_token_ids, batch_segment_ids, batch_labels.flatten()], None

# 加载数据集
train_dataloader = DataLoader(MyDataset(['F:/Projects/data/corpus/sentence_classification/sentiment/sentiment.train.data']), batch_size=batch_size, shuffle=True, collate_fn=collate_fn) 

# 定义bert上的模型结构，这里loss并不是放在模型里计算的
class Model(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.bert = build_transformer_model(config_path=config_path, checkpoint_path=checkpoint_path, with_pool=True)
        self.dropout = nn.Dropout(0.1)
        self.dense = nn.Linear(self.bert.configs['hidden_size'], 2)
        self.loss_fn = nn.CrossEntropyLoss()

    def forward(self, token_ids, segment_ids, labels):
        _, pooled_output = self.bert([token_ids, segment_ids])
        output = self.dropout(pooled_output)
        output = self.dense(output)
        loss = self.loss_fn(output, labels)
        return loss
model = Model().to(device)
model = BaseModelDP(model)  # 方式一：指定DP模型使用多gpu
# model = add_trainer(nn.DataParallel(model))  # 方式二：指定DP模型使用多gpu

# 定义使用的loss和optimizer，这里支持自定义
model.compile(
    loss=lambda x, _: x.mean(),  # 多个gpu计算的loss的均值
    optimizer=optim.Adam(model.parameters(), lr=2e-5),
)

if __name__ == '__main__':
    model.fit(train_dataloader, epochs=20, steps_per_epoch=None)
