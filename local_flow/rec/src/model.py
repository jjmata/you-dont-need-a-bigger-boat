"""

Train and LSTM model for intent prediction with using Weights & Biases for tracking

"""
import wandb
import gensim
import numpy as np
from random import choice
from utils import return_json_file_content

from dataclasses import dataclass
from prodb.prodb import ProdB

@dataclass
class ProdBConfig():
    MAX_LEN = 20
    BATCH_SIZE = 32
    LR = 0.001
    EMBED_DIM = 128
    NUM_HEAD = 8
    MASKING_PROBABILITY = 0.25
    DATA_RATIO = 10  # dummy variable, we used this to understand if data size had an effect
    FF_DIM = 128
    NUM_LAYERS = 1
    EPOCHS = 1
    VOCAB_SIZE = 0


def train_prodb_model(dataset: dict):

    # convert into prodb input format
    train_sessions = [ ' '.join(_) for _ in dataset['train']]

    # limit test sessions to last 20 interactions only
    test_sessions = [' '.join(_[-20:]) for _ in dataset['valid']]

    # initialize prodb
    config = ProdBConfig()
    config.VOCAB_SIZE = len( { _ for s in  dataset['train'] for _ in s  } )
    prodb_model = ProdB(train_sessions, config)

    # make predictions on test sessions
    prodb_model.run_next_item_predictions(test_sessions[:1])



    # return MLM weights and token mappings
    return {
                'model': prodb_model.bert_masked_model.to_json(),
                'weights': prodb_model.bert_masked_model.get_weights(),
                'custom_objects': { prodb_model.MaskedLanguageModel.__name__:prodb_model.MaskedLanguageModel }
            },\
           {
                'token2id': prodb_model.token2id,
                'id2token': prodb_model.id2token
           }


def train_prod2vec_model(sessions: dict,
                          min_c: int = 3,
                          size: int = 48,
                          window: int = 5,
                          iterations: int = 15,
                          ns_exponent: float = 0.75):
    """
    Train CBOW to get product embeddings. We start with sensible defaults from the literature - please
    check https://arxiv.org/abs/2007.14906 for practical tips on how to optimize prod2vec.

    :param sessions: list of lists, as user sessions are list of interactions
    :param min_c: minimum frequency of an event for it to be calculated for product embeddings
    :param size: output dimension
    :param window: window parameter for gensim word2vec
    :param iterations: number of training iterations
    :param ns_exponent: ns_exponent parameter for gensim word2vec
    :return: trained product embedding model
    """
    model =  gensim.models.Word2Vec(sentences=sessions['train'],
                                    min_count=min_c,
                                    vector_size=size,
                                    window=window,
                                    epochs=iterations,
                                    ns_exponent=ns_exponent)

    print("# products in the space: {}".format(len(model.wv.index_to_key)))

    make_predictions(model.wv, sessions['valid'])


    return model.wv


def make_predictions(prod2vec_model, sessions):
    cnt_preds = 0
    my_predictions = []
    # get all possible SKUs in the model, as a back-up choice
    all_skus = list(prod2vec_model.index_to_key)
    print("Some SKUS.. {}".format(all_skus[:2]))
    test_queries = sessions
    hits = 0
    # loop over the records and predict the next event
    for t in test_queries:
        # this is our prediction, which defaults to a random SKU
        next_sku = choice(all_skus)
        target = t[-1]
        _products_in_session = t[:-1]
        # get last product in the query session and check it is in the model space
        if _products_in_session and _products_in_session[-1] in all_skus:
                # get first product from knn
                next_sku = prod2vec_model.similar_by_word(_products_in_session[-1], topn=1)[0][0]
                cnt_preds += 1

        if next_sku == target:
            hits+=1


    # print out some "coverage"
    print("Predictions made in {} out of {} total test cases".format(cnt_preds, len(test_queries)))
    # check hit rate as metric
    print("HR : {}".format(hits/len(test_queries)))

    wandb.log({"HR": hits / len(test_queries)})

    return