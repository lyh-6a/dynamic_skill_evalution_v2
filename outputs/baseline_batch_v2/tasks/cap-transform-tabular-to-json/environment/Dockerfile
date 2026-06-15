FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3 python3-pip \
 \
    && rm -rf /var/lib/apt/lists/*

# Preinstall the verifier framework (pytest + ctrf reporter) so test.sh
# runs immediately. If the candidate skill ships a ``requirements.txt``
# the runner merges it here at build time too (convenience — agent gets
# skill deps without a runtime pip install). The agent is free to
# ``pip install`` or ``apt-get install`` additional packages at runtime;
# the evaluation measures whether it *followed the skill*, not whether it
# managed without internet.
RUN pip3 install --no-cache-dir --break-system-packages \
    --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    pytest==8.4.1 \
    pytest-json-ctrf==0.3.5

WORKDIR /root

# Inputs for this task
COPY input.csv /root/input.csv
