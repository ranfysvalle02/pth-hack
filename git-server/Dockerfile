FROM alpine:3.19

RUN apk add --no-cache openssh git bash && \
    ssh-keygen -A && \
    adduser -D -s /bin/bash git && \
    passwd -u git && \
    mkdir -p /home/git/.ssh /repos && \
    chown -R git:git /home/git /repos

COPY authorized_keys /home/git/.ssh/authorized_keys
COPY sshd_config /etc/ssh/sshd_config
COPY init-repo.sh /init-repo.sh
RUN chmod 600 /home/git/.ssh/authorized_keys && \
    chown git:git /home/git/.ssh/authorized_keys && \
    chmod +x /init-repo.sh

RUN /init-repo.sh

EXPOSE 22
CMD ["/usr/sbin/sshd", "-D", "-e"]
