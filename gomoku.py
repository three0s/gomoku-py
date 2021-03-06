import math
import time
import numpy as np
from functools import reduce
import os.path
import json
from cachetools import LRUCache
from multiprocessing import Process
import multiprocessing
import logging

#logging.basicConfig(filename='example.log',level=logging.DEBUG)
global_sub_row_eval = [{}, {}]
# this doesn't help much I feel, removed
global_row_cache = LRUCache(maxsize=100000)
global_board_cache = LRUCache(maxsize=10000)
# fourth layer of caching, plan to implement multithreaded stuff with this
global_transposition = LRUCache(maxsize=1000)
board_cache_hit = 0
row_cache_hit = 0
manager = multiprocessing.Manager()
transposition_tbl = manager.dict()

# make it write/read to disk for faster start up


def precompute_gobal_sub_row():
    global global_sub_row_eval

    str_key_eval={}
    if os.path.isfile("sub_row_dump0.json") and os.path.isfile("sub_row_dump1.json"):
        with open('sub_row_dump0.json', 'r') as f:
            try:
                str_key_eval = json.load(f)
                #oh well, integral keys are dumped as strings...
                for k,v in str_key_eval.items():
                    global_sub_row_eval[0][int(k)] = v

            except ValueError:
                global_sub_row_eval[0] = {}

        with open('sub_row_dump1.json', 'r') as f:
            try:
                str_key_eval = json.load(f)
                for k,v in str_key_eval.items():
                    global_sub_row_eval[1][int(k)] = v
            except ValueError:
                global_sub_row_eval[1] = {}

    if len(global_sub_row_eval[1]) == 0 or len(global_sub_row_eval[0]) == 0:

        g = Gomoku(np.arange(225), 15, 15)
        # preprocess haha
        for row in range(1, 1 << 16):
            g.count_consec_row(row, 0)
            g.count_consec_row(row, 1)
            if row % (math.floor((1 << 16) / 100)) == 0:
                print("progress..", math.floor(row / ((1 << 16) / 100)))

        with open('sub_row_dump0.json', 'w') as f:
            json.dump(global_sub_row_eval[0], f)
        with open('sub_row_dump1.json', 'w') as f:
            json.dump(global_sub_row_eval[1], f)


class Gomoku(object):

    def __init__(self, board_list, size_x=None, size_y=None, global_eval_dict=None, patterns=None):
        self.size_x = size_x or 15
        self.size_y = size_y or 15
        self.board = np.array(board_list).reshape(self.size_x, self.size_y)
        # print(self.board)
        # self.board = board_list[:]

        if patterns is None:
            self.patterns = {}
            self.add_p(0b1010, (1, 1))  # _O_
            self.add_p(0b101, (2, 2))  # _OX
            self.add_p(0b10110, (20, 20))  # _OO_
            self.add_p(0b101010, (20, 20))  # _O_O_
            self.add_p(0b1011, (3, 3))  # _OOX
            self.add_p(0b101110, (1500, 10000))  # _OOO_
            self.add_p(0b10111, (20, 20))  # _OOOX
            self.add_p(0b1011010, (1500, 10000))  # _OO_O_
            self.add_p(0b101011, (20, 20))  # _O_OOX
            self.add_p(0b1011110, (10000, 10000000))  # _OOOO_
            self.add_p(0b10110110, (1500, 10000))  # _OO_OO_
            self.add_p(0b10111010, (20, 10000))  # _OOO_O_
            self.add_p(0b101111, (100, 10000))  # _OOOOX
            self.add_p(0b1011011, (20, 10000))  # _OO_OOX
            self.add_p(0b1011101, (20, 10000))  # _OOO_OX
            self.add_p(0b111111, (8000000, 8000000))  # XOOOOOX
            self.add_p(0b10111110, (10000000, 10000000))  # _OOOOO_
            self.add_p(0b1011111, (8000000, 8000000))  # _OOOOOX

        self.max_pattern_len = reduce(
            (lambda x, y: max(x, y.bit_length() - 1)), self.patterns.keys(), 0)

    def add_p(self, p, v):
        self.patterns[p] = v

    def __get_p(self, x, y):
        return self.board[x][y]

    def __put_p(self, x, y, p):
        self.board[x][y] = p

    def put_p(self, x, y, p):
        self.board[x][y] = p

    def __empty_p(self):
        return 1

    def row_add_p(self, row, p):
        return (row << 1) | p

    def check_winner(self):
        # up, up-right, right, down-right, down, down-left, left, up-left
        dirx = [0, 1, 1, 1, 0, -1, -1, -1]
        diry = [-1, -1, 0, 1, 1, 1, 0, -1]
        for x in range(0, self.size_x):
            for y in range(0, self.size_y):
                cur_piece = self.__get_p(x, y)
                if cur_piece == 0:
                    continue
                for dx, dy in zip(dirx, diry):
                    count = 0
                    nx = x
                    ny = y
                    for j in range(0, 4):
                        nx = nx + dx
                        ny = ny + dy
                        if nx >= 0 and nx < 15 and ny >= 0 and ny < 15:
                            if self.__get_p(nx, ny) != cur_piece:
                                break
                            else:
                                count += 1
                        else:
                            break
                    if count == 4:
                        return cur_piece.item()
        return 0

    def row_is_set(self, row, idx, rlen):
        return (row & (1 << (rlen - 1 - idx))) != 0

    def row_splice(self, row, pos, rlen):
        # basically zeroing out stuff and stick a 1
        row &= ~(1 << rlen)
        for i in range(0, pos):
            row &= ~(1 << rlen - 1 - i)
        row |= 1 << (rlen - pos)
        return row

    def row_length(self, row):
        return row.bit_length() - 1

    def row_startswith(self, row, p):
        len1 = row.bit_length()
        len2 = p.bit_length()
        if len1 < len2:
            return False
        return (row >> (len1 - len2)) == p

    def row_reverse(self, row):
        rlen = row.bit_length()
        backward_row = self.__empty_p()
        for i in range(0, rlen - 1):
            if (row & (1 << i)) != 0:
                backward_row = (backward_row << 1) ^ 1
            else:
                backward_row = (backward_row << 1)
        return backward_row

    # can probably preprocess this
    # 2^15 combinations, seems resonable
    def row_dper(self, row, dp, idx, etype):
        # print(row)
        #print(bin(row), idx)
        cur_max = 0
        row_len = self.row_length(row)
        if row_len < 3:
            dp[idx] = 0
            return 0
        saved_val = dp[idx]
        if not saved_val == -1:
            return saved_val

        # skip empty spaces
        if not self.row_is_set(row, 0, row_len) and not self.row_is_set(row, 1, row_len):
            #print(bin(row),"will be skipping first 0")
            return self.row_dper(self.row_splice(row, 1, row_len), dp, idx + 1, etype)

        for p, p_eval_tuple in self.patterns.items():
            p_eval = p_eval_tuple[etype]
            p_len = self.row_length(p)
            rp = self.row_reverse(p)
            if self.row_startswith(row, rp):
                #print("detected rp",bin(row),bin(rp))
                cur_val = p_eval + \
                    self.row_dper(self.row_splice(
                        row, p_len, row_len), dp, idx + p_len, etype)
                cur_max = max(cur_val, cur_max)
            if self.row_startswith(row, p):
                #print("detected p",bin(row),bin(p))
                cur_val = p_eval + \
                    self.row_dper(self.row_splice(
                        row, p_len, row_len), dp, idx + p_len, etype)
                cur_max = max(cur_val, cur_max)

        # move on, do nothing
        cur_val = self.row_dper(self.row_splice(
            row, 1, row_len), dp, idx + 1, etype)
        cur_max = max(cur_val, cur_max)

        dp[idx] = cur_max
        return cur_max

    def init_dp(self, row):
        # length of row
        rlen = self.row_length(row)
        dp = [-1] * (rlen)
        for i in range(0, self.max_pattern_len):
            dp.append(0)
        return (dp, rlen)

    # new matching algorithm
    # dynamic programming using heuristic to select the best for a row
    # aggregate for all rows of different directions
    def count_consec_row(self, row, etype):
        global global_sub_row_eval
        global_row_cache
        global board_cache_hit

        if row <= (1 << 5):
            return 0

        # better way to do this? I don't like composite key
        if row in global_sub_row_eval[etype]:
            return global_sub_row_eval[etype][row]

        # does not contain any 'O'
        for i in range(0, 17):
            if row == 1 << i:
                global_sub_row_eval[etype][row] = 0
                return 0

        (dp_forward, rlen) = self.init_dp(row)
        dp_backward = dp_forward[:]

        forward = self.row_dper(row, dp_forward, 0, etype)

        backward_row = self.row_reverse(row)
        backward = self.row_dper(backward_row, dp_backward, 0, etype)

        ret = max(forward, backward)
        global_sub_row_eval[etype][row] = ret
        return ret

    def count_rowx(self, x, y, dx, dy, cur, etype):
        opponent = 2 if cur == 1 else 1
        row = self.__empty_p()
        cur_score = 0
        for i in range(0, max(self.size_x, self.size_y)):
            if x < 0 or x >= self.size_x or y < 0 or y >= self.size_y:
                break
            p = self.__get_p(x, y)
            x += dx
            y += dy
            if p == opponent:
                cur_score += self.count_consec_row(row, etype)
                row = self.__empty_p()
                continue
            row = self.row_add_p(row, 0 if p == 0 else 1)
        cur_score += self.count_consec_row(row, etype)

        return cur_score

    def count_rowy(self, cur, etype, row_arr):
        global global_row_cache
        global row_cache_hit

        opponent = 2 if cur == 1 else 1

        rowkey = tuple(row_arr) + (cur, etype)
        # if rowkey in global_row_cache:
        #     #print("this too is useful")
        #     row_cache_hit += 1
        #     return global_row_cache[rowkey]

        row = self.__empty_p()
        cur_score = 0
        for p in row_arr:
            if p == opponent:
                cur_score += self.count_consec_row(row, etype)
                row = self.__empty_p()
                continue
            row = self.row_add_p(row, 0 if p == 0 else 1)
        cur_score += self.count_consec_row(row, etype)

        #global_row_cache[rowkey] = cur_score

        return cur_score

    def count_boardx(self, cur, etype):
        global global_board_cache
        global board_cache_hit

        # dumb hashing, whatever

        board_hash = tuple(map(tuple, self.board)) + (cur, etype)
        if board_hash in global_board_cache:
            board_cache_hit += 1
            return global_board_cache[board_hash]

        val = 0

        for i in range(0, self.size_x):
            val += self.count_rowy(cur, etype, self.board.diagonal(-i))
        for i in range(1, self.size_y):
            val += self.count_rowy(cur, etype, self.board.diagonal(i))
        for i in range(0, self.size_x):
            val += self.count_rowy(cur, etype, self.board[i])
        for i in range(0, self.size_y):
            val += self.count_rowy(cur, etype, self.board[:, i])
        for i in range(0, self.size_x):
            val += self.count_rowy(cur, etype,
                                   np.rot90(self.board).diagonal(i))
        for i in range(1, self.size_y):
            val += self.count_rowy(cur, etype,
                                   np.rot90(self.board).diagonal(-i))

        global_board_cache[board_hash] = val

        return val

    def count_board(self, cur, etype):
        # dirx = [0, 1, 1, 1]
        # diry = [1, -1, 1, 0]
        val = 0

        # this is slow
        # use numpy functions to speed it up

        # vertical
        for i in range(0, self.size_y):
            val += self.count_rowx(0, i, 1, 0, cur, etype)

        # horizontal
        for i in range(0, self.size_y):
            val += self.count_rowx(i, 0, 0, 1, cur, etype)

        # diagonal \
        for i in range(0, self.size_y):
            val += self.count_rowx(0, i, 1, 1, cur, etype)
        for i in range(1, self.size_x):
            val += self.count_rowx(i, 0, 1, 1, cur, etype)

        # diagonal /
        for i in range(0, self.size_y):
            val += self.count_rowx(0, i, 1, -1, cur, etype)
        for i in range(1, self.size_x):
            val += self.count_rowx(i, self.size_y - 1, 1, -1, cur, etype)

        return val

    def get_next_move(self, cur):
        global board_cache_hit
        global global_board_cache
        global row_cache_hit
        global global_transposition

        # refresh...memory is actually an issue
        # it'll be great if I can save every table in memory...
        #global_board_cache = [{}, {}]
        board_cache_hit = 0
        row_cache_hit = 0
        opponent = 2 if cur == 1 else 1
        (v, x, y) = self.alphabeta(1, -9999999,
                                   9999999, True, 2, 1, global_transposition)
        if x == -1 and y == -1:  # lost already
            (v, x, y) = self.get_best_moves(
                cur, opponent)[0]  # just do whatever
        #print("board cache hit", board_cache_hit)
        #print("row cache hit", row_cache_hit)
        return (x, y)

    def get_next_move_multi(self, cur):
        (x, y) = self.multiproc_alphabeta(1)
        if x == -1 and y == -1:  # lost already
            (v, x, y) = self.get_best_moves(2, 1)[0]  # just do whatever
        return (x,y)

    def get_best_moves(self, cur, opponent):
        min_x = math.floor(self.size_x / 2)
        max_x = math.ceil(self.size_x / 2)
        min_y = math.floor(self.size_y / 2)
        max_y = math.ceil(self.size_y / 2)
        for x in range(0, self.size_x):
            for y in range(0, self.size_y):
                if self.__get_p(x, y) != 0:
                    min_x = min(x, min_x)
                    max_x = max(x, max_x)
                    min_y = min(y, min_y)
                    max_y = max(y, max_y)
        min_x -= 2
        max_x += 2
        min_y -= 2
        max_y += 2
        min_x = max(0, min_x)
        max_x = min(self.size_x, max_x)
        min_y = max(0, min_y)
        max_y = min(self.size_y, max_y)

        l = []
        for x in range(min_x, max_x):
            for y in range(min_y, max_y):
                if self.__get_p(x, y) == 0:
                    # t = time.process_time()
                    self.__put_p(x, y, cur)
                    score = self.count_boardx(cur, 0)
                    # if the player can win right away - don't do anything else
                    if score >= self.patterns[0b111111][0]:
                        self.__put_p(x, y, 0)
                        return [(1, x, y)]
                    score -= self.count_boardx(opponent, 0)
                    self.__put_p(x, y, opponent)
                    score += self.count_boardx(opponent, 0)
                    l.append((score, x, y))
                    self.__put_p(x, y, 0)
                    # print("took ", time.process_time() - t)

        l = sorted(l, key=lambda x: x[0], reverse=True)
        return l[:12]

    # initiate 4 processes to compute stuff
    # lets see how it works on a Manager dict
    # then I can probably try memcached or give up this approach
    # -> just as slow, not sure whats the bottleneck
    def multiproc_alphabeta(self, depth):
        #lets kill memory
        global transposition_tbl
        #manager = multiprocessing.Manager()
        #transposition_tbl = manager.dict()

        cur = 2
        opponent = 1
        alpha = -9999999
        beta = 9999999

        best_moves = self.get_best_moves(cur, opponent)

        process_num = 4
        task_distribution = [0] * process_num
        node_num = len(best_moves)
        pid = 0
        while node_num > 0:
            task_distribution[pid] += 1
            node_num -= 1
            pid = (pid + 1) % process_num

        print("distribution",task_distribution)

        processes = []
        start_idx = 0
        for task_count in task_distribution:
            print("working on",best_moves[start_idx:start_idx + task_count])
            p = multiprocessing.Process(target=self.alphabeta, args=(depth,
                alpha, beta, True, cur, opponent, transposition_tbl, best_moves[start_idx:start_idx + task_count]))
            start_idx += task_count
            processes.append(p)
            p.start()

        for p in processes:
            p.join()

        best_x = -1
        best_y = -1
        best_val = -9999999

        for (s, x, y) in best_moves:
            # print("white",x,y)
            self.__put_p(x, y, cur)
            # (v, b_x, b_y) = self.alphabeta(
            #     depth - 1, alpha, beta, False, cur, opponent, transposition_tbl)
            board_hash = tuple(map(tuple, self.board)) + (False,)
            if board_hash in transposition_tbl:
                (v, b_x, b_y) = transposition_tbl[board_hash]
            else: 
                self.__put_p(x, y, 0)
                continue
            print("result ",v,x,y)
            if v > best_val:
                best_x = x
                best_y = y
                best_val = v
            self.__put_p(x, y, 0)

        return (best_x, best_y)

    def alphabeta(self, depth, alpha, beta, maximizing, cur, opponent, transposition, predefined_moves=None):

        board_hash = tuple(map(tuple, self.board))
        if board_hash in transposition:
            #print("board evaluated")
            return transposition[board_hash]

        winner = self.check_winner()
        if winner != 0:
            print("termination detected")
            ret = (self.count_boardx(cur, 0) -
                   self.count_boardx(opponent, 1), -1, -1)
            transposition[board_hash] = ret
            return ret

        if depth == 0:
            ret = (self.count_boardx(cur, 0) -
                   self.count_boardx(opponent, 1), -1, -1)
            transposition[board_hash] = ret
            return ret

        best_x = -1
        best_y = -1
        best_val = 0

        if maximizing:
            best_val = -9999999
            if predefined_moves is None:
                best_moves = self.get_best_moves(cur, opponent)
            else:
                best_moves = predefined_moves
            for (s, x, y) in best_moves:
                # print("white",x,y)
                self.__put_p(x, y, cur)
                (v, b_x, b_y) = self.alphabeta(
                    depth - 1, alpha, beta, False, cur, opponent, transposition)
                if v > best_val:
                    best_x = x
                    best_y = y
                    best_val = v
                self.__put_p(x, y, 0)
                alpha = max(alpha, best_val)
                if beta <= alpha:
                    # print("pruned")
                    break
        else:
            best_val = 9999999
            best_moves = []

            for (s, x, y) in self.get_best_moves(opponent, cur):
                self.__put_p(x, y, opponent)
                (v, b_x, b_y) = self.alphabeta(
                    depth - 1, alpha, beta, True, cur, opponent, transposition)
                if v < best_val:
                    best_x = x
                    best_y = y
                    best_val = v
                self.__put_p(x, y, 0)
                beta = min(beta, best_val)
                if beta <= alpha:
                    # print("pruned")
                    break

        

        transposition[board_hash] = (best_val, best_x, best_y)

        return (best_val, best_x, best_y)
