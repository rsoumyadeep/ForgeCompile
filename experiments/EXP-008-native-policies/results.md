| policy | native time (geomean vs fc-O0) | worst | .text size | interp cost | passes | decision ms | pass ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| llvm-O2 | 0.137 | 0.890 | 0.604 | 1.000 | 0.0 | 0.0 | 0.0 |
| frequency | 0.837 | 1.028 | 0.929 | 0.747 | 11.0 | 0.0 | 2.0 |
| O2 | 0.850 | 1.088 | 0.870 | 0.741 | 12.0 | 0.0 | 2.3 |
| model:gradient_boosting | 0.855 | 1.119 | 0.969 | 0.815 | 5.1 | 93.0 | 1.0 |
| oracle-greedy | 0.861 | 1.088 | 1.019 | 0.741 | 4.5 | 12446.7 | 1.0 |
| O1 | 0.885 | 1.016 | 0.882 | 0.925 | 5.0 | 0.0 | 0.7 |
| 012:dqn_scaled_seed0+noretry | 0.945 | 1.006 | 0.912 | 0.906 | 12.0 | 7.6 | 1.7 |
| 006:dqn_seed0+noretry | 0.952 | 1.027 | 0.975 | 0.884 | 6.0 | 3.9 | 1.1 |
| 012:dqn_scaled_seed0 | 0.986 | 1.029 | 0.970 | 0.966 | 12.0 | 5.7 | 1.0 |
| 006:dqn_seed0 | 0.988 | 1.005 | 0.993 | 0.894 | 6.1 | 3.4 | 1.3 |
| fc-O0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0 | 0.0 | 0.0 |

| benchmark | policy | native ratio | CV | size ratio | passes |
|---|---|---:|---:|---:|---|
| arith_hash | fc-O0 | 1.000 | 0.2% | 1.000 |  |
| arith_hash | O1 | 1.001 | 0.3% | 0.970 | constfold,copyprop,simplify,dce,simplifycfg |
| arith_hash | O2 | 1.088 | 0.1% | 1.030 | inline,sccp,copyprop,simplify,cse,licm,strength,bce,constfold,copyprop,dce,simplifycfg |
| arith_hash | frequency | 1.001 | 0.3% | 1.060 | simplifycfg,dce,copyprop,sccp,licm,constfold,simplify,inline,cse,strength,bce |
| arith_hash | model:gradient_boosting | 1.001 | 0.1% | 0.970 | constfold,dce,copyprop,simplifycfg |
| arith_hash | oracle-greedy | 1.088 | 0.1% | 1.030 | copyprop,strength,simplifycfg |
| arith_hash | 006:dqn_seed0 | 1.001 | 0.1% | 1.000 | constfold,copyprop,copyprop,copyprop,licm,licm,licm,licm |
| arith_hash | 006:dqn_seed0+noretry | 1.001 | 0.3% | 0.970 | constfold,copyprop,copyprop,constfold,licm,cse,simplifycfg,licm,licm |
| arith_hash | 012:dqn_scaled_seed0 | 1.001 | 0.2% | 1.000 | copyprop,constfold,simplify,sccp,simplify,sccp,simplify,simplify,simplify,simplify,simplify,simplify |
| arith_hash | 012:dqn_scaled_seed0+noretry | 1.001 | 0.1% | 0.970 | copyprop,constfold,simplify,sccp,copyprop,simplifycfg,simplify,sccp,copyprop,constfold,dce,copyprop |
| arith_hash | llvm-O2 | 0.890 | 0.4% | 0.752 |  |
| branch_classify | fc-O0 | 1.000 | 3.3% | 1.000 |  |
| branch_classify | O1 | 0.846 | 2.5% | 0.889 | constfold,copyprop,simplify,dce,simplifycfg |
| branch_classify | O2 | 0.850 | 2.5% | 0.889 | inline,sccp,copyprop,simplify,cse,licm,strength,bce,constfold,copyprop,dce,simplifycfg |
| branch_classify | frequency | 0.849 | 3.7% | 0.926 | simplifycfg,dce,copyprop,sccp,licm,constfold,simplify,inline,cse,strength,bce |
| branch_classify | model:gradient_boosting | 0.846 | 4.4% | 0.889 | copyprop,simplifycfg |
| branch_classify | oracle-greedy | 0.846 | 2.3% | 0.889 | copyprop,simplifycfg |
| branch_classify | 006:dqn_seed0 | 0.999 | 2.9% | 1.000 | constfold,sccp,sccp,copyprop,copyprop,copyprop,licm,licm,licm,licm,licm |
| branch_classify | 006:dqn_seed0+noretry | 0.849 | 4.0% | 0.926 | constfold,sccp,copyprop,copyprop,constfold,licm,cse,simplifycfg,licm,licm,cse |
| branch_classify | 012:dqn_scaled_seed0 | 0.996 | 3.5% | 1.000 | copyprop,simplify,simplify,simplify,simplify,simplify,simplify,simplify,simplify,simplify,simplify,simplify |
| branch_classify | 012:dqn_scaled_seed0+noretry | 0.998 | 4.3% | 1.000 | copyprop,simplify,dce,copyprop,simplify,dce,cse,licm,bce,sccp,inline,constfold |
| branch_classify | llvm-O2 | 0.238 | 1.1% | 0.381 |  |
| call_fib | fc-O0 | 1.000 | 1.0% | 1.000 |  |
| call_fib | O1 | 1.000 | 2.0% | 0.968 | constfold,copyprop,simplify,dce,simplifycfg |
| call_fib | O2 | 0.996 | 3.5% | 0.968 | inline,sccp,copyprop,simplify,cse,licm,strength,bce,constfold,copyprop,dce,simplifycfg |
| call_fib | frequency | 0.998 | 2.8% | 0.968 | simplifycfg,dce,copyprop,sccp,licm,constfold,simplify,inline,cse,strength,bce |
| call_fib | model:gradient_boosting | 1.001 | 3.0% | 1.000 | constfold,copyprop |
| call_fib | oracle-greedy | 1.010 | 3.0% | 0.968 | copyprop,simplifycfg |
| call_fib | 006:dqn_seed0 | 0.997 | 1.0% | 1.000 | constfold,constfold,constfold,constfold,constfold,constfold,constfold,constfold,constfold,constfold,constfold,constfold |
| call_fib | 006:dqn_seed0+noretry | 1.012 | 2.3% | 1.000 | constfold,constfold,sccp,simplify,constfold,sccp,simplify,cse,bce,strength,copyprop,constfold |
| call_fib | 012:dqn_scaled_seed0 | 1.000 | 4.6% | 1.000 | constfold,constfold,constfold,constfold,constfold,constfold,constfold,constfold,constfold,constfold,constfold,constfold |
| call_fib | 012:dqn_scaled_seed0+noretry | 0.999 | 5.4% | 0.968 | constfold,constfold,sccp,copyprop,constfold,sccp,copyprop,simplifycfg,constfold,sccp,copyprop,simplifycfg |
| call_fib | llvm-O2 | 0.585 | 4.9% | 0.704 |  |
| call_helpers | fc-O0 | 1.000 | 0.9% | 1.000 |  |
| call_helpers | O1 | 1.000 | 0.8% | 0.949 | constfold,copyprop,simplify,dce,simplifycfg |
| call_helpers | O2 | 0.848 | 0.8% | 1.026 | inline,sccp,copyprop,simplify,cse,licm,strength,bce,constfold,copyprop,dce,simplifycfg |
| call_helpers | frequency | 0.810 | 3.9% | 1.102 | simplifycfg,dce,copyprop,sccp,licm,constfold,simplify,inline,cse,strength,bce |
| call_helpers | model:gradient_boosting | 0.848 | 0.5% | 1.026 | constfold,inline,dce,simplifycfg,copyprop |
| call_helpers | oracle-greedy | 0.849 | 0.8% | 1.026 | inline,simplifycfg,copyprop,simplifycfg |
| call_helpers | 006:dqn_seed0 | 1.003 | 4.6% | 1.000 | sccp,sccp,copyprop,copyprop,copyprop,licm,licm,licm,licm |
| call_helpers | 006:dqn_seed0+noretry | 1.027 | 1.7% | 0.974 | sccp,sccp,copyprop,copyprop,licm,cse,simplifycfg,licm,licm |
| call_helpers | 012:dqn_scaled_seed0 | 1.003 | 2.5% | 1.000 | copyprop,copyprop,copyprop,copyprop,copyprop,copyprop,copyprop,copyprop,copyprop,copyprop,copyprop,copyprop |
| call_helpers | 012:dqn_scaled_seed0+noretry | 1.000 | 4.5% | 0.974 | copyprop,copyprop,simplifycfg,simplifycfg,licm,simplifycfg,copyprop,sccp,dce,sccp,simplifycfg,licm |
| call_helpers | llvm-O2 | 0.625 | 1.0% | 0.765 |  |
| loop_nest | fc-O0 | 1.000 | 4.0% | 1.000 |  |
| loop_nest | O1 | 0.838 | 3.0% | 0.685 | constfold,copyprop,simplify,dce,simplifycfg |
| loop_nest | O2 | 1.022 | 0.3% | 0.842 | inline,sccp,copyprop,simplify,cse,licm,strength,bce,constfold,copyprop,dce,simplifycfg |
| loop_nest | frequency | 1.028 | 1.1% | 0.860 | simplifycfg,dce,copyprop,sccp,licm,constfold,simplify,inline,cse,strength,bce |
| loop_nest | model:gradient_boosting | 0.688 | 1.0% | 0.737 | dce,constfold,simplifycfg,copyprop,licm,simplifycfg,simplify |
| loop_nest | oracle-greedy | 1.031 | 0.6% | 1.035 | licm,copyprop,strength,simplifycfg,constfold |
| loop_nest | 006:dqn_seed0 | 0.885 | 5.1% | 1.018 | sccp,sccp,sccp,copyprop,licm,licm,licm,licm |
| loop_nest | 006:dqn_seed0+noretry | 0.696 | 3.4% | 0.965 | sccp,sccp,copyprop,licm,licm,cse,simplifycfg,licm,licm |
| loop_nest | 012:dqn_scaled_seed0 | 0.843 | 2.1% | 0.877 | copyprop,simplifycfg,copyprop,simplifycfg,copyprop,simplifycfg,copyprop,simplifycfg,copyprop,simplifycfg,copyprop,simplifycfg |
| loop_nest | 012:dqn_scaled_seed0+noretry | 0.835 | 9.4% | 0.685 | copyprop,simplifycfg,copyprop,simplifycfg,constfold,copyprop,simplifycfg,cse,dce,simplifycfg,constfold,simplify |
| loop_nest | llvm-O2 | 0.002 | 10.5% | 0.366 |  |
| matrix_matmul | fc-O0 | 1.000 | 0.3% | 1.000 |  |
| matrix_matmul | O1 | 0.689 | 0.3% | 0.843 | constfold,copyprop,simplify,dce,simplifycfg |
| matrix_matmul | O2 | 0.670 | 0.4% | 0.806 | inline,sccp,copyprop,simplify,cse,licm,strength,bce,constfold,copyprop,dce,simplifycfg |
| matrix_matmul | frequency | 0.660 | 0.4% | 1.019 | simplifycfg,dce,copyprop,sccp,licm,constfold,simplify,inline,cse,strength,bce |
| matrix_matmul | model:gradient_boosting | 0.705 | 0.5% | 1.305 | dce,constfold,copyprop,simplifycfg,cse,licm,strength,inline,simplifycfg |
| matrix_matmul | oracle-greedy | 0.655 | 0.5% | 1.139 | licm,copyprop,bce,strength,simplifycfg,cse,inline,simplifycfg |
| matrix_matmul | 006:dqn_seed0 | 1.000 | 0.4% | 1.000 | simplify,copyprop |
| matrix_matmul | 006:dqn_seed0+noretry | 1.001 | 0.4% | 1.000 | simplify,copyprop |
| matrix_matmul | 012:dqn_scaled_seed0 | 1.000 | 0.3% | 1.000 | constfold,constfold,constfold,constfold,constfold,constfold,constfold,simplify,constfold,simplify,constfold,simplify |
| matrix_matmul | 012:dqn_scaled_seed0+noretry | 0.715 | 0.3% | 0.954 | constfold,constfold,simplify,simplifycfg,constfold,simplify,simplifycfg,licm,constfold,simplify,simplifycfg,constfold |
| matrix_matmul | llvm-O2 | 0.052 | 1.0% | 0.628 |  |
| matrix_stencil | fc-O0 | 1.000 | 2.8% | 1.000 |  |
| matrix_stencil | O1 | 1.016 | 1.1% | 0.900 | constfold,copyprop,simplify,dce,simplifycfg |
| matrix_stencil | O2 | 0.754 | 1.6% | 0.710 | inline,sccp,copyprop,simplify,cse,licm,strength,bce,constfold,copyprop,dce,simplifycfg |
| matrix_stencil | frequency | 0.750 | 0.4% | 0.710 | simplifycfg,dce,copyprop,sccp,licm,constfold,simplify,inline,cse,strength,bce |
| matrix_stencil | model:gradient_boosting | 0.881 | 1.5% | 0.840 | constfold,dce,copyprop,simplifycfg,cse |
| matrix_stencil | oracle-greedy | 0.678 | 1.8% | 1.300 | licm,cse,copyprop,bce,simplifycfg,inline,constfold,simplifycfg |
| matrix_stencil | 006:dqn_seed0 | 1.005 | 3.5% | 0.920 | sccp,sccp,sccp,sccp,sccp,copyprop |
| matrix_stencil | 006:dqn_seed0+noretry | 1.001 | 1.1% | 0.920 | sccp,sccp,copyprop |
| matrix_stencil | 012:dqn_scaled_seed0 | 1.004 | 2.0% | 0.920 | constfold,dce,constfold,constfold,constfold,dce,constfold,dce,constfold,dce,constfold,simplify |
| matrix_stencil | 012:dqn_scaled_seed0+noretry | 1.006 | 1.5% | 0.890 | constfold,dce,constfold,dce,copyprop,copyprop,sccp,strength,constfold,licm,copyprop,sccp |
| matrix_stencil | llvm-O2 | 0.048 | 10.2% | 0.588 |  |
| memory_sieve | fc-O0 | 1.000 | 2.0% | 1.000 |  |
| memory_sieve | O1 | 0.810 | 3.8% | 0.813 | constfold,copyprop,simplify,dce,simplifycfg |
| memory_sieve | O2 | 0.725 | 5.5% | 0.792 | inline,sccp,copyprop,simplify,cse,licm,strength,bce,constfold,copyprop,dce,simplifycfg |
| memory_sieve | frequency | 0.724 | 3.1% | 0.792 | simplifycfg,dce,copyprop,sccp,licm,constfold,simplify,inline,cse,strength,bce |
| memory_sieve | model:gradient_boosting | 0.810 | 3.9% | 0.813 | constfold,copyprop,simplifycfg,dce,simplifycfg |
| memory_sieve | oracle-greedy | 0.962 | 5.5% | 0.896 | copyprop,bce,simplifycfg |
| memory_sieve | 006:dqn_seed0 | 0.997 | 1.4% | 1.000 | sccp,copyprop |
| memory_sieve | 006:dqn_seed0+noretry | 0.994 | 1.6% | 1.000 | sccp,copyprop |
| memory_sieve | 012:dqn_scaled_seed0 | 1.029 | 3.2% | 0.917 | simplifycfg,simplifycfg,simplifycfg,simplifycfg,simplifycfg,simplifycfg,simplifycfg,simplifycfg,simplifycfg,simplifycfg,simplifycfg,simplifycfg |
| memory_sieve | 012:dqn_scaled_seed0+noretry | 0.967 | 1.3% | 0.896 | simplifycfg,simplifycfg,copyprop,copyprop,sccp,strength,constfold,licm,bce,simplify,copyprop,inline |
| memory_sieve | llvm-O2 | 0.295 | 2.5% | 0.559 |  |
| memory_sort | fc-O0 | 1.000 | 1.0% | 1.000 |  |
| memory_sort | O1 | 0.980 | 0.5% | 0.882 | constfold,copyprop,simplify,dce,simplifycfg |
| memory_sort | O2 | 0.967 | 1.2% | 0.941 | inline,sccp,copyprop,simplify,cse,licm,strength,bce,constfold,copyprop,dce,simplifycfg |
| memory_sort | frequency | 1.016 | 1.2% | 1.220 | simplifycfg,dce,copyprop,sccp,licm,constfold,simplify,inline,cse,strength,bce |
| memory_sort | model:gradient_boosting | 1.119 | 2.1% | 1.294 | constfold,copyprop,inline,dce,simplifycfg,cse,cse,simplifycfg |
| memory_sort | oracle-greedy | 0.919 | 0.2% | 1.264 | copyprop,bce,simplifycfg,inline,constfold,simplifycfg,cse |
| memory_sort | 006:dqn_seed0 | 1.004 | 0.2% | 1.000 | copyprop |
| memory_sort | 006:dqn_seed0+noretry | 1.000 | 5.7% | 1.000 | copyprop |
| memory_sort | 012:dqn_scaled_seed0 | 1.001 | 0.5% | 1.000 | copyprop,copyprop,copyprop,copyprop,copyprop,copyprop,copyprop,copyprop,copyprop,copyprop,copyprop,copyprop |
| memory_sort | 012:dqn_scaled_seed0+noretry | 0.979 | 6.3% | 0.838 | copyprop,copyprop,sccp,copyprop,sccp,strength,constfold,licm,bce,simplify,constfold,dce |
| memory_sort | llvm-O2 | 0.196 | 3.2% | 0.718 |  |
| vector_saxpy | fc-O0 | 1.000 | 0.3% | 1.000 |  |
| vector_saxpy | O1 | 0.747 | 0.3% | 0.966 | constfold,copyprop,simplify,dce,simplifycfg |
| vector_saxpy | O2 | 0.698 | 0.5% | 0.763 | inline,sccp,copyprop,simplify,cse,licm,strength,bce,constfold,copyprop,dce,simplifycfg |
| vector_saxpy | frequency | 0.653 | 1.7% | 0.763 | simplifycfg,dce,copyprop,sccp,licm,constfold,simplify,inline,cse,strength,bce |
| vector_saxpy | model:gradient_boosting | 0.749 | 1.5% | 0.966 | constfold,copyprop,simplifycfg,dce |
| vector_saxpy | oracle-greedy | 0.699 | 0.4% | 0.763 | copyprop,bce,simplifycfg |
| vector_saxpy | 006:dqn_seed0 | 1.001 | 1.3% | 1.000 | sccp,copyprop |
| vector_saxpy | 006:dqn_seed0+noretry | 1.001 | 1.4% | 1.000 | sccp,copyprop |
| vector_saxpy | 012:dqn_scaled_seed0 | 1.000 | 0.5% | 1.000 | simplify,constfold,simplify,constfold,simplify,constfold,simplify,constfold,simplify,constfold,simplify,constfold |
| vector_saxpy | 012:dqn_scaled_seed0+noretry | 1.000 | 0.8% | 1.000 | simplify,constfold,simplify,constfold,simplify,bce,strength,dce,constfold,simplify,bce,strength |
| vector_saxpy | llvm-O2 | 0.092 | 1.3% | 0.777 |  |
